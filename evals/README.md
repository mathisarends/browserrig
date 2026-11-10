# WebArena-Verified Hard

Browserrig runs a frozen **48-task subset of WebArena-Verified Hard**, replacing the
previous practice/reference/wild benchmark. Tasks and grading rules come unchanged
from [ServiceNow/WebArena-Verified](https://github.com/ServiceNow/webarena-verified)
**v1.2.3**, commit `6473f72db5dcefc97b5725b59e734504edc28a21`.

## Frozen dataset

[The manifest](data/manifest.json) records exact IDs, source hashes, subset hash,
selection seed and algorithm. The sample has 10 tasks each for Shopping, Shopping
Admin, GitLab and Reddit, plus 8 cross-site tasks. Those include Map and Wikipedia.
There are 29 mutation, 13 retrieval and 6 navigation tasks.

Selection uses site quotas, proportional operation quotas and template diversity,
with SHA-256 tie-breaking. It uses no agent scores and never resamples at runtime.
This is a deliberately balanced development subset, not an unbiased estimate of
all 258 Hard tasks. Report it as **browserrig-webarena-verified-hard-48-v1**,
not as a full WebArena-Verified Hard score. Keep separate tasks for final evaluation
if you repeatedly tune against these 48.

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

# Select frozen IDs or filter by site / operation.
uv run --no-sync python -m evals.run --tasks 29,106,116 --headed
uv run --no-sync python -m evals.run --tasks @retrieve --repeat 2
```

Default authentication uses the existing subscription provider `openai-codex`,
with model `gpt-6.1-terra`. Run `codex login` first. Explicit `--provider openai`
uses `OPENAI_API_KEY` and optionally `OPENAI_MODEL`; `--model` overrides the model.
There is no automatic fallback between providers.

Each attempt recreates its websites, signs into the public benchmark accounts,
opens the original start URLs, records a full embedded-content HAR, runs Browserrig,
flushes the HAR, then invokes the unmodified official evaluator. Containers
are explicitly initialized with their base URL after startup; this
handles the current image CLI's required parameter. Browser locale is fixed to
English (en-US) and timezone to UTC, including the automated login context.
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

## Reproduce the freeze

```powershell
git clone https://github.com/ServiceNow/webarena-verified.git .browserrig/webarena-verified-upstream
git -C .browserrig/webarena-verified-upstream checkout 6473f72db5dcefc97b5725b59e734504edc28a21
uv run --no-sync python -m evals.freeze .browserrig/webarena-verified-upstream
```

Do not regenerate during normal evaluation. Intentional changes require a new
subset version and baseline. The imported data is Apache-2.0 licensed; see
[data/NOTICE](data/NOTICE) and [upstream license](data/LICENSE.webarena-verified).
