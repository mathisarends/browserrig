"""Build a standalone, evidence-backed HTML report from compatible suite shards."""

import argparse
import json
import os
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, Field

from . import analyze, network_evidence
from .network_evidence import DocumentVisit, NetworkRequest
from .results import BenchmarkResult, TaskResult, ToolRecord, write_run
from .task import Task, load_tasks

ASSETS = Path(__file__).with_name("report_assets")
PATTERNS = {
    "Klicken / Zielauswahl": {"click", "click_at", "move_mouse"},
    "Formulare / Texteingabe": {"type_text", "send_keys", "set_date"},
    "Dropdowns": {"select_option"},
    "Scrollen": {"scroll"},
    "Navigation / Suche": {
        "navigate",
        "search",
        "go_back",
        "go_forward",
        "reload",
        "find_in_page",
    },
    "Tabs": {"open_tab", "switch_tab", "close_tab", "list_tabs"},
    "Dialoge": {"handle_dialog"},
    "Drag & Drop": {"drag", "drag_at"},
    "Warten": {"wait"},
    "Dateien": {"read_file", "write_file", "upload_files", "list_files"},
}


class Finding(BaseModel):
    category: str
    title: str
    confidence: Literal["Beobachtet", "Hypothese"]
    evidence: list[str]
    fix: str
    source: Literal["Regel", "Trace-Review"] = "Regel"
    session_id: str | None = None


class ReportTask(BaseModel):
    task_id: int
    intent: str
    sites: list[str]
    action: str
    status: Literal["pass", "fail", "error", "pending", "blocked"]
    reason: str | None = None
    record: TaskResult | None = None
    tools: list[ToolRecord] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    grade: dict[str, Any] = Field(default_factory=dict)
    requests: list[NetworkRequest] = Field(default_factory=list)
    documents: list[DocumentVisit] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)
    trace_id: str | None = None
    trace_error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tokens_source: str | None = None


class HtmlReport(BaseModel):
    name: str
    dataset_sha256: str
    generated: str
    revision: str
    runs: list[str]
    model: str
    provider: str
    max_steps: int | None
    timeout: int | None
    pattern_tools: dict[str, list[str]]
    setup_attempts: dict[str, str] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    tasks: list[ReportTask]


def build(
    paths: list[Path],
    output: Path,
    blocked: dict[int, str],
    revision: str,
    *,
    refresh: bool = False,
) -> HtmlReport:
    manifest, tasks = load_tasks()
    runs = [BenchmarkResult.model_validate_json(path.read_bytes()) for path in paths]
    if not runs:
        raise ValueError("No suite results available yet")
    if set(blocked) - set(manifest.task_ids):
        raise ValueError("Blocked IDs must belong to the frozen subset")
    baseline = runs[0]
    records: dict[int, TaskResult] = {}
    for run in runs:
        if run.dataset_sha256 != manifest.tasks_sha256 or (
            run.model,
            run.provider,
            run.max_steps,
            run.timeout,
        ) != (baseline.model, baseline.provider, baseline.max_steps, baseline.timeout):
            raise ValueError(
                "Cannot merge different datasets, models, providers or budgets"
            )
        for record in run.tasks:
            task_id = record.task_id
            if task_id is None or task_id not in manifest.task_ids:
                raise ValueError(f"Unexpected suite task ID: {task_id}")
            if task_id in records:
                raise ValueError(
                    f"Duplicate task {task_id}; do not silently pick the best attempt"
                )
            if task_id in blocked:
                raise ValueError(f"Executed task {task_id} is also marked blocked")
            records[task_id] = record
    cache = output.parent / (output.stem + "-evidence")
    cache.mkdir(parents=True, exist_ok=True)
    views = [
        _task_view(
            task,
            records.get(task.task_id),
            blocked.get(task.task_id),
            baseline.project,
            cache=cache,
            output=output,
            refresh=refresh,
        )
        for task in tasks
    ]
    reviews_path = output.with_suffix(".reviews.json")
    if reviews_path.is_file():
        reviews = json.loads(reviews_path.read_bytes())
        for view in views:
            if view.record is None:
                continue
            notes = [
                Finding.model_validate(note)
                for note in reviews.get(str(view.task_id), [])
            ]
            notes = [
                note
                for note in notes
                if note.source != "Trace-Review"
                or (
                    note.session_id is not None
                    and note.session_id == view.record.session_id
                )
            ]
            view.findings = notes + view.findings
    report = HtmlReport(
        name=manifest.name,
        dataset_sha256=manifest.tasks_sha256,
        generated=datetime.now(UTC).isoformat(),
        revision=revision,
        runs=[str(path.resolve()) for path in paths],
        model=baseline.model,
        provider=baseline.provider,
        max_steps=baseline.max_steps,
        timeout=baseline.timeout,
        pattern_tools={name: sorted(tools) for name, tools in PATTERNS.items()},
        setup_attempts=_setup_attempts(paths[0].parent, output),
        runtime=json.loads(output.with_suffix(".runtime.json").read_bytes())
        if output.with_suffix(".runtime.json").is_file()
        else {},
        tasks=views,
    )
    _write(output, report)
    merged = baseline.model_copy(
        update={
            "run": output.stem,
            "selection": ",".join(
                str(task.task_id) for task in tasks if task.task_id not in blocked
            ),
            "tasks": [
                records[task.task_id] for task in tasks if task.task_id in records
            ],
        }
    )
    write_run(output.with_suffix(".run.json"), merged)
    return report


def _task_view(
    task: Task,
    record: TaskResult | None,
    blocked: str | None,
    project: str,
    *,
    cache: Path,
    output: Path,
    refresh: bool,
) -> ReportTask:
    view = ReportTask(
        task_id=task.task_id,
        intent=task.intent,
        sites=list(task.sites),
        action=task.action,
        status="blocked" if blocked else "pending",
        reason=blocked,
    )
    if record is None:
        return view
    view.record, view.status = record, record.status
    workspace = Path(record.workspace).resolve()
    for name, filename in (
        ("HAR", "network.har"),
        ("Evaluator", "eval_result.json"),
        ("Antwort", "agent_response.json"),
        ("Nachrichten", "messages.json"),
        ("Setup-Log", "environment.log"),
    ):
        path = workspace / filename
        if path.is_file():
            view.links[name] = _relative(path, output)
    grade = workspace / "eval_result.json"
    if grade.is_file():
        view.grade = network_evidence.redact(json.loads(grade.read_bytes()))
    request_cache = cache / f"{record.task}-{record.attempt}-network.json"
    if request_cache.is_file() and not refresh:
        view.requests = [
            NetworkRequest.model_validate(item)
            for item in json.loads(request_cache.read_bytes())
        ]
    else:
        view.requests = network_evidence.requests(workspace)
        request_cache.write_text(
            json.dumps([request.model_dump(mode="json") for request in view.requests]),
            encoding="utf-8",
        )
    spans = _spans(record, project, cache, refresh, view)
    documents_cache = cache / f"{record.task}-{record.attempt}-documents.json"
    if documents_cache.is_file() and not refresh:
        view.documents = [
            DocumentVisit.model_validate(item)
            for item in json.loads(documents_cache.read_bytes())
        ]
    else:
        view.documents = network_evidence.documents(workspace)
        documents_cache.write_text(
            json.dumps([item.model_dump() for item in view.documents]), encoding="utf-8"
        )
    traced_tools = _trace_tools(spans)
    view.tools = (
        traced_tools if len(traced_tools) >= len(record.tools) else record.tools
    )
    if spans:
        view.metrics = analyze.analyze(record, project, cache, spans=spans)
        view.trace_id = spans[0].get("context", {}).get("trace_id")
        view.links["Trace JSON"] = _relative(
            cache / f"{record.session_id}.json", output
        )
        view.links["Kontext-Dump"] = _relative(
            cache / f"{record.task}-{record.attempt}.md", output
        )
        view.links["Phoenix"] = "http://127.0.0.1:6006/"
    _trace_coverage(view, spans, traced_tools)
    _tokens(view, spans)
    names = {tool.name for tool in view.tools}
    view.patterns = [pattern for pattern, tools in PATTERNS.items() if names & tools]
    view.findings = _findings(view)
    return view


def _spans(
    record: TaskResult, project: str, cache: Path, refresh: bool, view: ReportTask
) -> list[dict]:
    if record.session_id is None:
        return []
    path = cache / f"{record.session_id}.json"
    try:
        spans = json.loads(path.read_bytes()) if path.is_file() and not refresh else []
        if not spans:
            spans = analyze.px_spans(project, record.session_id)
            if spans:
                path.write_text(json.dumps(spans, ensure_ascii=False), encoding="utf-8")
        return spans
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        view.trace_error = f"{type(error).__name__}: {error}"
        return []


def _trace_coverage(
    view: ReportTask, spans: list[dict], tools: list[ToolRecord]
) -> None:
    record = view.record
    assert record is not None
    if record.session_id is None:
        return
    if not spans:
        view.metrics["trace_coverage"] = "missing"
        view.trace_error = (
            view.trace_error or "Keine Phoenix-Spans für diese Session verfügbar."
        )
        return
    if record.usage is None or record.tool_calls is None:
        view.metrics["trace_coverage"] = "unknown"
        return
    prompt = sum(
        span["attributes"].get("llm.token_count.prompt", 0)
        for span in spans
        if span["name"] == "harnessed.model"
    )
    complete = prompt == record.usage.input and len(tools) == record.tool_calls
    view.metrics["trace_coverage"] = "complete" if complete else "partial"
    if not complete:
        view.trace_error = (
            f"Teilweiser Trace: {prompt}/{record.usage.input} Eingabetokens "
            f"und {len(tools)}/{record.tool_calls} Toolaufrufe in Phoenix. "
            "Für Toolmuster werden vollständige lokale Toolaufzeichnungen bevorzugt."
        )


def _trace_tools(spans: list[dict]) -> list[ToolRecord]:
    tools = []
    for span in sorted(spans, key=lambda item: item["start_time"]):
        if span["name"] != "harnessed.tool":
            continue
        attributes = span["attributes"]
        arguments = _json_value(attributes.get("input.value", "{}"))
        content = _json_value(attributes.get("output.value", ""))
        text = (
            content
            if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False)
        )
        tools.append(
            ToolRecord(
                name=attributes.get("tool.name", "unknown"),
                args=arguments if isinstance(arguments, dict) else str(arguments),
                error=str(attributes.get("harnessed.tool.is_error", False)).lower()
                == "true",
                chars=len(text),
                preview=text[:2000],
            )
        )
    return tools


def _json_value(value):
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _tokens(view: ReportTask, spans: list[dict]) -> None:
    if view.record is not None and view.record.usage is not None:
        view.input_tokens, view.output_tokens = (
            view.record.usage.input,
            view.record.usage.output,
        )
        view.tokens_source = "Agent usage"
        return
    models = [span["attributes"] for span in spans if span["name"] == "harnessed.model"]
    if models and all("llm.token_count.prompt" in attributes for attributes in models):
        view.input_tokens = sum(
            attributes["llm.token_count.prompt"] for attributes in models
        )
        view.output_tokens = sum(
            attributes.get("llm.token_count.completion", 0) for attributes in models
        )
        view.tokens_source = (
            "Phoenix: abgeschlossene Modellaufrufe; ggf. laufenden Aufruf nicht erfasst"
        )


def _findings(view: ReportTask) -> list[Finding]:
    record = view.record
    assert record is not None
    findings = []
    errors = [tool for tool in view.tools if tool.error]
    if errors:
        findings.append(
            Finding(
                category="tool-errors",
                title="Browser-Tools melden Fehler",
                confidence="Beobachtet",
                evidence=[f"{tool.name}: {tool.preview[:550]}" for tool in errors[:6]],
                fix="Fehler nach Tool und Ziel gruppieren. Bei fehlenden oder veralteten Refs "
                "zuerst "
                "neu beobachten, dann Ziel erneut auflösen. Für reproduzierbare Fälle einen "
                "Integrationstest in tools/targeting bzw. observation ergänzen.",
            )
        )
    failed_checks = [check for check in record.checks if not check.ok]
    findings.extend(_payload_findings(view))
    if record.status == "fail" and record.completed:
        fixes = {
            "retrieve": (
                "Datenabruf / Aggregation",
                "Filterkriterien und verlangte Ausgabefelder vor "
                "der Antwort explizit prüfen. Alle relevanten Seiten/Pagination lesen "
                "und Zählungen "
                "gegen konkrete Belege abgleichen; zuerst die Assertion-Differenz untersuchen.",
            ),
            "navigate": (
                "Zielseite / Navigationskriterien",
                "Vor done die endgültige Zielseite und "
                "alle Filter prüfen. Bei AND-/Negationsbedingungen die gesamte Bedingung testen; "
                "erforderliche Query-Parameter und Ergebnisse nach Navigation verifizieren.",
            ),
            "mutate": (
                "Änderung nicht vollständig verifiziert",
                "Nach Absenden auf bestätigten "
                "Zielzustand warten und die Änderung durch erneutes Lesen verifizieren. Die "
                "geforderte Mutation mit dem tatsächlichen Request und dessen Payload vergleichen.",
            ),
        }
        title, fix = fixes[view.action]
        findings.append(
            Finding(
                category=f"semantic-{view.action}",
                title=title,
                confidence="Hypothese",
                evidence=[
                    f"{check.label}: {check.detail or 'fehlgeschlagen'}"
                    for check in failed_checks
                ]
                or [
                    "Agent meldet Abschluss; der offizielle Evaluator lehnt das Ergebnis ab."
                ],
                fix=fix,
            )
        )
    if record.completed is False or record.stop_reason in {
        "timeout",
        "max_steps",
        "token_budget",
    }:
        findings.append(
            Finding(
                category="budget",
                title="Aufgabe innerhalb des Budgets nicht abgeschlossen",
                confidence="Beobachtet",
                evidence=[f"Stop-Grund: {record.stop_reason}"],
                fix="Im Verlauf die letzten erfolgreichen Zustandswechsel suchen. "
                "Wiederholte Aktionen "
                "früher abbrechen und eine neue Strategie verlangen. Erst nach dieser Diagnose "
                "das Zeit- oder Schrittbudget erhöhen; Vergleichsläufe mit gleichem Budget halten.",
            )
        )
    counts = Counter(
        (tool.name, json.dumps(tool.args, sort_keys=True))
        for tool in view.tools
        if tool.name not in {"wait", "scroll", "list_tabs"}
    )
    repetitions = [
        f"{name} {arguments[:220]}: {count} Aufrufe"
        for (name, arguments), count in counts.items()
        if count >= 3
    ]
    if repetitions:
        findings.append(
            Finding(
                category="repetition",
                title="Wiederholte identische Toolargumente",
                confidence="Beobachtet",
                evidence=repetitions[:5],
                fix="Prüfen, ob die Wiederholung nötig war oder der Agent "
                "keinen Fortschritt erkannt hat. Gleiche Ref-Nummern können auf verschiedenen "
                "Seiten andere Ziele meinen; deshalb den Kontext-Dump daneben prüfen. Bei "
                "bestätigter Schleife Fortschrittsprüfung und Recovery im Agenten ergänzen.",
            )
        )
    if view.metrics.get("obs_max", 0) >= 15_000:
        findings.append(
            Finding(
                category="context",
                title="Sehr große Seitenbeobachtung",
                confidence="Beobachtet",
                evidence=[
                    f"Größte Beobachtung: {view.metrics['obs_max']:,} Zeichen; "
                    f"größter Prompt: {view.metrics.get('prompt_max', 0):,} Tokens"
                ],
                fix="Den größten Schritt im Kontext-Dump prüfen. Wiederholte Navigation, lange "
                "Tabellen und irrelevante Seitenteile gezielt reduzieren. Danach Tokenverbrauch "
                "und Erfolgsrate gemeinsam vergleichen; keine Belege wegkürzen, "
                "die der Agent braucht.",
            )
        )
    if record.status == "error":
        findings.append(
            Finding(
                category=f"infra-{record.error_phase}",
                title="Lauf- oder Evaluatorfehler",
                confidence="Beobachtet",
                evidence=[f"Phase {record.error_phase}: {record.error}"],
                fix="Zuerst Setup-/Evaluator-Log und Trace prüfen. Infrastrukturfehler "
                "reparieren und gesondert wiederholen; dieses Ergebnis nicht als "
                "fachliche Agentenschwäche zählen.",
            )
        )
    return findings


def _payload_findings(view: ReportTask) -> list[Finding]:
    differences = network_evidence.differences(view.grade, view.requests)
    if not differences:
        return []
    return [
        Finding(
            category="payload",
            title="Gesendete Formularfelder weichen von der Referenz ab",
            confidence="Beobachtet",
            evidence=[
                f"{item.field}\nErwartet: {item.expected}\nGesendet: {item.actual}"
                for item in differences[:8]
            ],
            fix="Zuerst die abweichenden Felder prüfen. Bei Bild-/Linkquellen den Originalbeitrag "
            "im richtigen Forum öffnen und die Quelle eindeutig zuordnen; gleichnamige Suchtreffer "
            "nicht als identisch behandeln. Bei Forum/Projekt/Kategorie vor dem Absenden den "
            "Zielkontext bestätigen. Danach genau diese Aufgabe mit gleichem Budget erneut testen. "
            "Dieser Diagnosevergleich ändert den offiziellen Score nicht.",
        )
    ]


def _setup_attempts(directory: Path, output: Path) -> dict[str, str]:
    archived = {}
    for path in directory.glob("setup-only-*suite-*.json"):
        run = BenchmarkResult.model_validate_json(path.read_bytes())
        if any(
            record.session_id is not None
            or record.usage is not None
            or record.error_phase != "setup"
            for record in run.tasks
        ):
            raise ValueError(
                f"An archived setup-only run contains agent execution: {path}"
            )
        archived[path.name] = _relative(path, output)
    return archived


def _relative(path: Path, output: Path) -> str:
    return quote(
        os.path.relpath(path.resolve(), output.resolve().parent).replace("\\", "/"),
        safe="/.",
    )


def _write(output: Path, report: HtmlReport) -> None:
    payload = report.model_dump_json().replace("<", "\\u003c")
    template = Template((ASSETS / "report.html").read_text("utf-8"))
    html = template.substitute(
        data=payload, script=(ASSETS / "report.mjs").read_text("utf-8")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output)
    output.with_suffix(".data.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--glob",
        required=True,
        help="Results filename glob, e.g. 20261110-*suite-*.json",
    )
    parser.add_argument(
        "--directory", type=Path, default=Path(__file__).with_name("results")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blocked", default="")
    parser.add_argument("--blocked-reason", default="Environment unavailable")
    parser.add_argument("--revision", default="unknown")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--expected", type=int, default=43)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    blocked = {
        int(task_id): args.blocked_reason
        for task_id in args.blocked.split(",")
        if task_id
    }
    while True:
        paths = sorted(
            path
            for path in args.directory.glob(args.glob)
            if not path.name.endswith((".analysis.json", ".data.json"))
        )
        report = build(paths, args.output, blocked, args.revision, refresh=args.refresh)
        counts = Counter(task.status for task in report.tasks)
        print(f"Report: {args.output}; {dict(counts)}", flush=True)
        completed = sum(counts[status] for status in ("pass", "fail", "error"))
        if not args.watch or completed >= args.expected:
            return
        time.sleep(20)


if __name__ == "__main__":
    main()
