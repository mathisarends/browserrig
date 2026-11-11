# WebArena-Verified Hard

Browserrig runs a frozen **48-task subset of WebArena-Verified Hard**, replacing the
previous practice/reference/wild benchmark. Tasks and grading rules come unchanged
from [ServiceNow/WebArena-Verified](https://github.com/ServiceNow/webarena-verified)
**v1.2.3**, commit `6473f72db5dcefc97b5725b59e734504edc28a21`.

## Frozen dataset

[The default local-v3 manifest](data/local-v3/manifest.json) records exact IDs,
source hashes, subset hash, selection seed and algorithm. It retains all 43
provisioned tasks from the original sample and replaces only its five
Map/Wikipedia-blocked slots. It needs Shopping, Shopping Admin, GitLab and Reddit,
with 11, 12, 14 and 15 task appearances respectively (cross-site tasks count toward
both sites). There are 29 mutation, 13 retrieval and 6 navigation tasks.

Within fixed site/operation strata, selection prefers least-used intent templates,
with SHA-256(seed:task_id) breaking ties. All five add a previously absent intent
template. Agent scores are not selection inputs:

| Blocked ID | Replacement | Added interaction coverage |
| --- | --- | --- |
| 267 | 66 | Read the ten hottest Books posts; select titles of posts recommending exactly one book |
| 428 | 709 | Set a date range from May 1, 2021 to March 31, 2022 in the admin orders report |
| 558 | 791 | Collect five Reddit URLs, preserve order, create a folder and JSON file in GitLab Web IDE, commit |
| 561 | 491 | Find a customer's latest pending order, use its message form and classify the application's rejection |
| 760 | 156 | Navigate to merge requests assigned to the current user |

This is an infrastructure-conditioned development sample. It does not measure
Map or Wikipedia capability. The [original-v1 manifest](data/manifest.json), task
definitions and historical results remain available; select them explicitly with
`--subset original-v1`.

The [local-v2 pilot](data/local-v2/manifest.json) and its smoke outcomes are retained.
That pilot exposed two independently checkable evaluator conflicts: task 68's
reference has `author: null` while its schema declares a string, and task 679
expects an Ajax filter request that the navigation grader excludes even when
present in the HAR. Local-v3 applies two narrow static screens to all replacement
candidates: reject reference null/type contradictions and NAVIGATE targets at
the Ajax-only `/mui/index/render` endpoint. These are not a complete schema or
evaluator audit. The original 43 tasks are unchanged. The same seed and strata
are retained, so only 68 and 679 change to 66 and 709. Failed agent attempts are
retained; task 491 remains selected despite its pilot failure.

Selection uses site quotas, proportional operation quotas and template diversity,
with SHA-256 tie-breaking. It uses no agent scores and never resamples at runtime.
This is a deliberately balanced development subset, not an unbiased estimate of
all 258 Hard tasks. Report the default as
**browserrig-webarena-verified-hard-local-48-v3**,
not as a full WebArena-Verified Hard score. Keep separate tasks for final evaluation
if you repeatedly tune against these 48.

The original sample is **browserrig-webarena-verified-hard-48-v1**. Its 29/43
historical result must not be combined with new runs to claim a current 48-task
score: the dataset and agent have changed. Compare the shared 43 tasks separately,
or execute all 48 under one recorded agent revision and budget.

The [2026-11-11 smoke audit](baselines/hard-local-48-v3-smoke-2026-11-11.json)
confirms that all five final replacements reached and completed an agent session.
Tasks 66, 156, 709 and 791 passed; 491 returned `UNKNOWN_ERROR` instead of the
expected `ACTION_NOT_ALLOWED_ERROR` after the application rejected its order
message. The observations span the pilot and follow-up, with identical definitions
for retained tasks, and are not a full-suite score. The pilot's initial GitLab
login failure is preserved; its follow-up passed after separating form submission
from the bounded post-login wait.

The original JSON definitions and evaluators are retained. Only concrete site URL
placeholders are resolved. Expected answers, evaluation rules, HARs and evaluator
configuration are outside the agent's Files workspace. The agent receives the
original intent and the upstream result schema.

The official evaluator requires its complete 812-task reference file internally.
We use the copy shipped with its pinned package and validate its checksum against
the manifest's upstream source hash. Only the 48 frozen IDs are executed or scored;
the other reference definitions cause no agent calls or token usage.

## Install and prepare

Use Python 3.12 or later, uv, local Chrome and Docker with Linux containers.

```powershell
uv sync --locked --group evals --extra openai --extra otel
uv sync --project evals/evaluator --locked --no-dev
uv run --no-sync python -m evals.run --list
```

The official evaluator has its own locked environment because its pinned Pydantic
version differs from Browserrig's. Playwright records HAR from the same installed
Chrome that Browserrig controls; no Playwright browser download is needed.

Website images and Map/Wikipedia datasets are large. The explicit setup command
downloads the official images and auxiliary data; allow substantial disk space and
download time. It does not run an agent:

```powershell
uv run --no-sync python -m evals.environments prepare
uv run --no-sync python -m evals.run --check
```

To start with only GitLab, use `prepare --sites gitlab`, followed by
`evals.run --tasks @gitlab --check`. The latter also includes cross-site GitLab
tasks, so prepare their sites too, or select numeric IDs instead.

[environments.json](environments.json) contains local URLs, control ports, image
names and upstream demo-account credentials. `--config PATH` and `--data-dir PATH`
override the config and auxiliary-data directory. Use dedicated benchmark
containers: upstream `env start` replaces containers named `webarena_verified_*`
on each attempt. Image tags follow upstream defaults; the dataset and evaluator
are pinned, while exact local image IDs are captured in preflight logs. Archive
these logs alongside a published result.

The normal runner checks Docker, local images and data before loading a model.
It never implicitly pulls multi-gigabyte images. Check/setup diagnostics go to
`.browserrig/webarena-*.log`.

## Run

```powershell
# One inexpensive first attempt; task 29 is part of the frozen subset.
uv run --no-sync python -m evals.run --tasks 29 --max-steps 30 --timeout 180

# All 48 tasks, with fixed default budgets: 50 steps and 300 agent seconds each.
uv run --no-sync python -m evals.run --trace --label baseline

# Smoke the five frozen replacements; retain failures as diagnostic evidence.
uv run --no-sync python -m evals.run --tasks 66,156,491,709,791 --label local-v3-smoke

# Reproduce membership of the historical version, including Map/Wikipedia.
uv run --no-sync python -m evals.run --subset original-v1 --list

# Select frozen IDs or filter by site / operation.
uv run --no-sync python -m evals.run --tasks 29,106,116 --headed
uv run --no-sync python -m evals.run --tasks @retrieve --repeat 2
```

Default authentication uses the existing subscription provider `openai-codex`,
with model `gpt-6.1-terra`. Run `codex login` first. Explicit `--provider openai`
uses `OPENAI_API_KEY` and optionally `OPENAI_MODEL`; `--model` overrides the model.

GPT-6.1 Terra uses the same model profile as regular Browserrig agents: a
256,000-token application context limit, 8,192-token output reserve, checkpoint
at 70%, compaction at 80%, two retained steps, a 40% input target and an
8,192-token summary ceiling. New result files record `context_window`,
`reserve_tokens`, `keep_last_steps`, `target_ratio` and `max_summary_tokens`.
Older baselines without these fields keep their original meaning.
There is no automatic fallback between providers.

Each attempt recreates its websites, signs into the public benchmark accounts,
opens the original start URLs, records a full embedded-content HAR, runs Browserrig,
flushes the HAR, then invokes the unmodified official evaluator. Containers
are explicitly initialized with their base URL after startup; this
handles the current image CLI's required parameter. Browser locale is fixed to
English (en-US) and timezone to UTC, including the automated login context.
Cross-site attempts use distinct `.localhost` hostnames when apps would otherwise
share a cookie domain. Ports do not isolate cookies: Reddit and Shopping both use
`PHPSESSID`. Each attempt saves its exact URL mappings for offline grading.
Shared mutable containers require `--parallel 1`; a process lock prevents overlapping runs from
this checkout. Resets and login are outside the agent time budget. A timeout or
unfinished session cannot pass. Cancellation closes the recording context and
preserves already written results.

The Bash convenience wrapper supports `all`, `list`, `check`, `prepare`,
`report`, `evaluate`, or frozen IDs / filters.

## Scores, artifacts and traces

The official evaluator checks the structured agent response and, where required,
network requests and responses. This produces a binary task score, without an LLM
judge. Infrastructure/evaluator errors are reported separately from task failures.
The report shows success counts over all attempts, scored means excluding errors,
per-site/operation breakdowns, tokens and elapsed time. Setup time is included in
elapsed time. Completed attempts are saved atomically.

Artifacts live in:

```text
evals/results/<run>.json
evals/results/workspaces/<run>/attempt-<n>/<task-id>/
  agent/                # agent-visible files only
  agent_response.json   # structured final response, or null if unfinished
  network.har           # full recorded network evidence
  environment.json      # evaluator URL mappings
  environment.log       # official reset diagnostics
  evaluator.log
  eval_result.json      # full upstream assertions and provenance checksums
```

Re-grade a saved attempt without a model or running website:

```powershell
uv run --no-sync python -m evals.evaluate evals/results/workspaces/<run>/attempt-1/29
uv run --no-sync python -m evals.report evals/results/<run>.json
```

Re-grading writes the attempt's `eval_result.json`; it does not rewrite the aggregate
run snapshot. Keep the pinned evaluator and dataset when moving artifacts.
Automatic run comparisons require
the same dataset hash and budgets. Historical custom-benchmark artifacts remain
readable but are not compared against this dataset.

For Phoenix, start `docker compose up -d --wait` and pass `--trace`. Existing
OTel export and `python -m evals.analyze` keep working; session IDs link task results
to traces. HARs and traces contain benchmark account/session data; keep artifacts
local or redact them before sharing.

## HTML diagnosis report

The first [sanitized baseline](baselines/hard-48-v1-terra-2026-11-10.json) records
29/43 official passes (67.4%), five infrastructure-blocked tasks, and one partial
trace. Review annotations flag potential evaluator sensitivities without changing
the official scores. Detailed HTML, HARs and trace exports remain local under
`evals/results/`.

Compatible suite shards can be combined into a standalone HTML report:

```powershell
uv run --no-sync python -m evals.html_report --glob '20261110-*suite-*.json' --output evals/results/webarena-hard-48-report.html --revision <agent-commit>
```

The report chooses the frozen version recorded in its input runs and includes
all 48 corresponding IDs. It rejects mixtures of original-v1, local-v2 and local-v3.
Missing results remain pending; for historical original-v1 reports use
`--blocked 267,428,558,561,760 --blocked-reason "..."` for infrastructure that
could not be provisioned. Blocked and pending tasks never receive invented scores.
`--watch --expected 43` updates the report as those 43 tasks finish. It rejects
duplicate task attempts and incompatible models, datasets or budgets.

The generator writes `.html`, `.data.json`, and a combined `.run.json`, plus cached
Phoenix evidence and context dumps beside the report. No model or LLM judge is
called. Interaction-pattern rates show task-level associations; tool error counts
refer only to the matching tools. Failure details include the official assertions,
recorded mutation requests, and literal expected-versus-sent form-field differences.
These diagnostic comparisons do not change upstream grading. Session/token fields
are redacted in the embedded request summaries; raw local artifacts are retained.
Optional `.reviews.json` files add explicitly labeled Codex trace reviews, bound to
the exact session IDs so findings cannot silently carry over to a different run.
Trace coverage checks model-token totals and tool counts against local results.
Incomplete traces are marked; complete local tool records are preferred when a
Phoenix export loses spans. New runs also retain `messages.json` when available.
The exporter uses small batches and a longer timeout by default, respecting explicit
OpenTelemetry environment overrides.

Corrections that failed before an agent session started may be retained as
`setup-only-*suite-*.json`. They are disclosed in the report and excluded from the
capability score; the generator verifies that they contain no agent sessions or
model usage. Actual agent failures must remain in the scored suite.

## Reproduce the freeze

```powershell
git clone https://github.com/ServiceNow/webarena-verified.git .browserrig/webarena-verified-upstream
git -C .browserrig/webarena-verified-upstream checkout 6473f72db5dcefc97b5725b59e734504edc28a21
uv run --no-sync python -m evals.freeze .browserrig/webarena-verified-upstream
uv run --no-sync python -m evals.freeze .browserrig/webarena-verified-upstream --pilot
uv run --no-sync python -m evals.freeze .browserrig/webarena-verified-upstream --local
```

Do not regenerate during normal evaluation. Intentional changes require a new
subset version and baseline. The imported data is Apache-2.0 licensed; see
[data/NOTICE](data/NOTICE) and [upstream license](data/LICENSE.webarena-verified).
