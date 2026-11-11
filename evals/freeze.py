"""Reproduce the frozen subset from the pinned, unmodified upstream checkout."""

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "1.2.3"
REVISION = "6473f72db5dcefc97b5725b59e734504edc28a21"
SUBSET = "browserrig-webarena-verified-hard-48-v1"
SEED = SUBSET
DATA = Path(__file__).with_name("data")
PILOT_DATA = DATA / "local-v2"
PILOT_SUBSET = "browserrig-webarena-verified-hard-local-48-v2"
LOCAL_DATA = DATA / "local-v3"
LOCAL_SUBSET = "browserrig-webarena-verified-hard-local-48-v3"
SUBSETS = {"original-v1": DATA, "local-v2": PILOT_DATA, "local-v3": LOCAL_DATA}
# Preserve operation counts; add content extraction, filtered navigation,
# cross-site structured editing, and an order workflow on provisioned sites.
REPLACEMENT_SLOTS = {
    267: ("reddit", "retrieve"),
    428: ("shopping_admin", "navigate"),
    558: ("gitlab+reddit", "mutate"),
    561: ("shopping_admin", "mutate"),
    760: ("gitlab", "navigate"),
}
QUOTAS = {
    "shopping": 10,
    "shopping_admin": 10,
    "gitlab": 10,
    "reddit": 10,
    "gitlab+reddit": 2,
    "gitlab+wikipedia": 2,
    "map+wikipedia": 2,
    "map+shopping_admin": 1,
    "reddit+shopping": 1,
}


def freeze(
    checkout: Path,
    output: Path | None = None,
    *,
    local: bool = False,
    pilot: bool = False,
) -> None:
    """Select by site, operation and template diversity, without using agent scores."""
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise ValueError(f"Expected upstream {REVISION}, got {revision}")
    # Read pinned Git blobs: checkout line endings and local edits cannot change the freeze.
    source = subprocess.check_output(
        [
            "git",
            "-C",
            str(checkout),
            "show",
            f"{REVISION}:assets/dataset/webarena-verified.json",
        ]
    )
    hard_source = subprocess.check_output(
        [
            "git",
            "-C",
            str(checkout),
            "show",
            f"{REVISION}:assets/dataset/subsets/webarena-verified-hard.json",
        ]
    )
    hard_ids = set(json.loads(hard_source)["task_ids"])
    tasks = json.loads(source)
    groups = defaultdict(list)
    for task in tasks:
        if task["task_id"] in hard_ids:
            groups["+".join(sorted(task["sites"]))].append(task)
    selected = []
    for group, count in QUOTAS.items():
        selected.extend(_sample(groups[group], count))
    selected.sort(key=lambda task: task["task_id"])
    payload = (json.dumps(selected, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    manifest = {
        "name": SUBSET,
        "upstream": "https://github.com/ServiceNow/webarena-verified",
        "version": VERSION,
        "revision": REVISION,
        "seed": SEED,
        "selection": "Site quotas; proportional operation quotas by largest remainder; "
        "prefer distinct intent templates; SHA-256(seed:task_id) breaks ties. "
        "No model results or task outcomes are used.",
        "quotas": QUOTAS,
        "task_ids": [task["task_id"] for task in selected],
        "hard_task_ids": sorted(hard_ids),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "hard_source_sha256": hashlib.sha256(hard_source).hexdigest(),
        "tasks_sha256": hashlib.sha256(payload).hexdigest(),
    }
    if local:
        selected, replacements, exclusions = _replace_blocked(
            tasks, hard_ids, selected, audit=not pilot
        )
        payload = (json.dumps(selected, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        manifest.update(
            name=PILOT_SUBSET if pilot else LOCAL_SUBSET,
            seed=PILOT_SUBSET,
            selection="Retain the original 43 provisioned tasks. Replace only the five "
            "Map/Wikipedia-blocked slots using fixed site/operation strata; prefer "
            "least-used intent templates, then SHA-256(seed:task_id). "
            "No agent scores, reference answers or smoke outcomes are used.",
            parent={"name": SUBSET, "tasks_sha256": manifest["tasks_sha256"]},
            replacement_reason="Map storage unavailable; Wikipedia source unavailable.",
            replacements=replacements,
            replacement_strata={
                str(task_id): {"sites": group.split("+"), "operation": operation}
                for task_id, (group, operation) in REPLACEMENT_SLOTS.items()
            },
            quotas=dict(
                sorted(Counter("+".join(sorted(t["sites"])) for t in selected).items())
            ),
            task_ids=[task["task_id"] for task in selected],
            tasks_sha256=hashlib.sha256(payload).hexdigest(),
        )
        if not pilot:
            manifest.update(
                selection="Retain the original 43 provisioned tasks and the pilot's "
                "site/operation strata and seed. Exclude replacement candidates "
                "with reference nulls forbidden by their declared schema types, "
                "or NAVIGATE targets at the Ajax-only /mui/index/render endpoint. "
                "Prefer least-used intent templates, then SHA-256(seed:task_id). "
                "No agent pass/fail outcomes are used as selection inputs.",
                excluded_candidates=exclusions,
                pilot_audit="The local-v2 smoke exposed two source-level evaluator "
                "conflicts. Its definitions and all outcomes are retained separately. "
                "The filters are static checks, not a complete evaluator audit.",
            )
    output = output or (
        PILOT_DATA if local and pilot else LOCAL_DATA if local else DATA
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "tasks.json").write_bytes(payload)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, help=f"Upstream checkout at {REVISION}")
    parser.add_argument(
        "--local", action="store_true", help="Freeze the provisioned local-v3 subset"
    )
    parser.add_argument("--pilot", action="store_true", help="Reproduce local-v2 pilot")
    args = parser.parse_args()
    freeze(args.checkout, local=args.local or args.pilot, pilot=args.pilot)


def _replace_blocked(
    tasks: list[dict], hard_ids: set[int], original: list[dict], *, audit: bool
) -> tuple[list[dict], dict[str, int], dict[str, str]]:
    used = {task["task_id"] for task in original}
    selected = [task for task in original if task["task_id"] not in REPLACEMENT_SLOTS]
    templates = Counter(task["intent_template_id"] for task in selected)
    replacements = {}
    exclusions = {}
    for old_id, (group, operation) in REPLACEMENT_SLOTS.items():
        candidates = [
            task
            for task in tasks
            if task["task_id"] in hard_ids - used
            and "+".join(sorted(task["sites"])) == group
            and task["eval"][0]["expected"]["task_type"] == operation
        ]
        issues = (
            {
                str(task["task_id"]): issue
                for task in candidates
                if (issue := _replacement_issue(task)) is not None
            }
            if audit
            else {}
        )
        exclusions.update(issues)
        candidates = [t for t in candidates if str(t["task_id"]) not in issues]
        if not candidates:
            raise ValueError(
                f"No Hard replacement for slot {old_id}: {group}/{operation}"
            )
        replacement = min(
            candidates,
            key=lambda task: (
                templates[task["intent_template_id"]],
                hashlib.sha256(
                    f"{PILOT_SUBSET}:{task['task_id']}".encode()
                ).hexdigest(),
            ),
        )
        selected.append(replacement)
        used.add(replacement["task_id"])
        templates[replacement["intent_template_id"]] += 1
        replacements[str(old_id)] = replacement["task_id"]
    return sorted(selected, key=lambda task: task["task_id"]), replacements, exclusions


def _replacement_issue(task: dict) -> str | None:
    response = task["eval"][0]
    action = response["expected"]["task_type"]
    if action == "retrieve" and _null_type_conflict(
        response["expected"].get("retrieved_data"), response.get("results_schema") or {}
    ):
        return (
            "Reference contains null where its declared result schema type forbids it."
        )
    if action == "navigate" and any(
        "/mui/index/render" in str(item["expected"].get("url", ""))
        and item["expected"].get("http_method", "GET") == "GET"
        for item in task["eval"]
        if item["evaluator"] == "NetworkEventEvaluator"
    ):
        return "Navigation evaluator filters out the Ajax-only target request."
    return None


def _null_type_conflict(value, schema: dict) -> bool:
    # A deliberately narrow consistency screen, not a general JSON Schema validator.
    types = schema.get("type", [])
    if isinstance(types, str):
        types = [types]
    if value is None:
        return bool(types) and "null" not in types
    if isinstance(value, list):
        return any(_null_type_conflict(item, schema.get("items", {})) for item in value)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        return any(
            _null_type_conflict(item, properties.get(key, {}))
            for key, item in value.items()
        )
    return False


def _sample(tasks: list[dict], count: int) -> list[dict]:
    operations = defaultdict(list)
    for task in tasks:
        action = task["eval"][0]["expected"]["task_type"]
        operations[action].append(task)
    quotas = {
        action: count * len(items) // len(tasks) for action, items in operations.items()
    }
    remainder = sorted(
        operations,
        key=lambda action: (-(count * len(operations[action]) % len(tasks)), action),
    )
    for action in remainder[: count - sum(quotas.values())]:
        quotas[action] += 1
    selected = []
    for action, quota in sorted(quotas.items()):
        candidates = sorted(
            operations[action],
            key=lambda task: hashlib.sha256(
                f"{SEED}:{task['task_id']}".encode()
            ).hexdigest(),
        )
        templates: Counter[int] = Counter()
        for _ in range(quota):
            task = min(
                candidates,
                key=lambda item, seen=templates: seen[item["intent_template_id"]],
            )
            candidates.remove(task)
            selected.append(task)
            templates[task["intent_template_id"]] += 1
    return selected


if __name__ == "__main__":
    main()
