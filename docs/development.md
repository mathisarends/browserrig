# Development

[Back to README](../README.md)

## Development

Development tools require Python >=3.12, uv, Node.js >=24, and pnpm 12.14.0.
Python sources live in `browserrig/`.

Keep public entry points before private helpers in modules, and public methods before
private methods in classes. Imports and prerequisite type or constant declarations come
first; preserve definition-time dependencies used by defaults, decorators and registries.
Apply this order to production code, tests and examples.
Within the same visibility, put callers before their helpers when definition-time
dependencies permit it.

```powershell
uv sync --locked --extra openai --extra ocr
pnpm.cmd install --frozen-lockfile
uv run prek install --overwrite
uv run prek run --all-files

uv run ruff check browserrig examples evals tests
uv run ruff format --check browserrig examples evals tests
uv run pylint browserrig examples evals tests
uv run ty check
uv run --locked smelt check --show-hints --fail-on warning
pnpm.cmd run lint
pnpm.cmd run format:check
uv run pytest                  # unit tests only (default)
uv run pytest -m integration   # real Chrome; `-m ""` runs everything
uv build
uv run --no-sync python tests/check_distribution.py
```

prek hooks use the uv and pnpm dependencies pinned in the lockfiles.
The existing `.pre-commit-config.yml` configures the checks; `--overwrite` replaces
any previously installed pre-commit hook.
Smelt is pinned to 0.6.0 through the same Python lockfile for local checks, hooks
and CI. Its hook runs on every commit, including configuration-only changes.
The checked-in `.smelt.schema.json` supplies offline editor validation for
`smelt.yml`; refresh it with `uv run --locked smelt config schema > .smelt.schema.json`
when upgrading Smelt.

The official Smelt agent skill and offline reference live in `.agents/skills/smelt`.
Refresh them after upgrading with `uv run --locked smelt skill install --force`.
Smelt 0.6.0 enables all six new reviews here: YAML files use `.yml` (except
the filename required by pnpm), Compose files use `compose`, and checks review
callable instances, private class constants, internal public attributes and
redundant module names. The `information-hiding` group also enables the review
of internal public module symbols; existing stricter individual severities remain.
Callable-instance suggestions remain advisory: action-chain policies implement
the named `check` protocol, while extraction and occlusion objects retain their
descriptive operations and reusable state. No public API rename is required.

The adopted rules review explicit `None` defaults, caller-before-helper order,
enum discriminator tags, class names, secret settings fields, module exports and
deterministic test inputs. `browserrig.kinds` retains a reasoned export exception
for its public compatibility facade. Module docstrings remain optional.
Inspect accepted findings with `uv run --locked smelt debt --show`.
After fixing findings, `uv run --locked smelt debt --prune` removes resolved entries
without accepting new debt. The grouped version-2 baseline requires Smelt >=0.5.0;
its nine existing accepted occurrences are preserved without rewriting the baseline.
On Linux and macOS, use `pnpm` instead of `pnpm.cmd` and `cp .env.example .env`
instead of `Copy-Item`.

JavaScript is checked with ESLint and Prettier: braces for every control block,
at most two nested blocks, and no nested ternary expressions. Pylint limits Python
blocks to three nesting levels; Ruff also checks for simplifications. CI runs the
same lint, formatting, and type checks. To format code, run
`uv run ruff format browserrig examples evals tests` and `pnpm.cmd run format`.

Integration tests require Chrome or Chromium. Set `BROWSERRIG_CHROME` or
`Chrome.launch(executable=...)` to select the executable. Media validation also
uses ffprobe when available.

## Distribution and release checks

The distribution check installs the built wheel and its runtime dependencies in a
temporary environment, checks JavaScript assets and typing data, and imports the
public API outside the checkout. CI runs it on every supported Python/OS pair.

Before publishing, run the checks above and the Chrome integration suite, review
`CHANGELOG.md`, and verify the package metadata and license in the built artifacts.

### Automated PyPI releases

`.github/workflows/release.yml` publishes through PyPI Trusted Publishing. It
reruns the complete CI suite on the selected commit, requires a release tag on
`main`, checks matching versions and changelog notes, and builds a wheel from the
source distribution. Twine checks the upload metadata and README, and the clean
wheel check verifies the actual artifact before a separate job uploads it to PyPI.
The publish job downloads these artifacts without checking out or rebuilding code.

The PyPI trusted publisher must use these values:

| Setting | Value |
| --- | --- |
| PyPI project | `browserrig` |
| GitHub owner | `mathisarends` |
| GitHub repository | `browserrig` |
| Workflow filename | `release.yml` |
| GitHub environment | `pypi` |

Create the `pypi` environment in the repository settings. Add required reviewers
there if publication should wait for a separate manual approval after creating the
tag or GitHub release. No PyPI API token or repository secret is needed. See the
[PyPI Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

To check the entire release process without publishing, select **Actions → Release
package → Run workflow** on `main`. This manual trigger runs CI and uploads the
verified distributions as a workflow artifact; it always skips the PyPI job.

To publish a version:

1. Prepare and merge a PR with the same version in `pyproject.toml` and
   `browserrig/__init__.py`. Keep `uv.lock` current (`uv lock`) and add the matching
   `## <version>` section to `CHANGELOG.md`, replacing any `unreleased` label with
   the release date. The `0.2.0` metadata and notes are prepared in this checkout.
2. Once `main` is green, manually publish a GitHub release with a matching tag,
   such as `v0.2.0`, targeting the prepared commit on `main`. Alternatively, push
   that tag yourself: `git tag v0.2.0 <commit>` and `git push origin v0.2.0`.
3. Watch **Actions → Release package** and approve the `pypi` environment if required
   reviewers are configured. Both stable and prerelease tags must exactly match
   `v` plus the Python package version (for example `v0.2.0rc1`).

Branch pushes, pull requests, draft GitHub releases and manual workflow runs do
not publish. A version tag push starts publication even if a GitHub release for
that tag is still a draft. Publishing a GitHub release for an already pushed tag
may start another run; runs for the same tag are serialized, and existing PyPI
files are skipped. For a transient failure, rerun the failed workflow rather than
moving a published tag. PyPI versions cannot be overwritten; changes need a new
version and tag. This setup PR creates no release or tag itself.

## Harnessed compatibility

Harnessed and all provider extras are pinned to the published 0.15.1 release.
`session.append_message(UserMessage(...))` adds durable background without starting
a turn. State format 2, checkpoint/store format 3 and audit envelope 5 reject older
data; back up old application data and start fresh stores.

`HumanHandoff.history` exposes typed, immutable receipts from session-owned state.
The plugin uses Harnessed's internal `PluginInstructions` only at its persistence
boundary. Its own `PrepareRequest` hook delivers current receipts as request-only
user messages. Keep this internal dependency inside the plugin; application code
uses `session.scope[HumanHandoff].history`. Verify restoration and model delivery
in `tests/handoff/test_handoff.py`, including after compaction.

The opt-in `Done` plugin uses native hooks for continuation and tool execution.
Its `PrepareOutput` hook defers native JSON constraints and the reserved
`final_answer` tool until the current turn has a successful `done` receipt.
`PrepareRequest` keeps the declared schema visible as guidance during work.
Both hooks compose with `next_()` and belong to the mounting scope; removing
the plugin restores native behavior. Plugins use the restricted `SessionContext`,
without recovering the application `Session`. Verify native/tool structured output, retries, limits,
streaming, overlapping sessions and runtime removal in
`tests/completion/test_completion.py`. `browserrig/completion/models.py` holds the
single table of tools each completion phase permits; the plugin enforces it through
`ToolPolicy` and `ExecuteTool` instead of withdrawing tool definitions.
`tests/test_agent_session_store.py` also checks reopening a paused `Done` turn with
`restore_outputs`, retained image assets and Browserrig's custom durable events.

`browser_tool` uses `harnessed.kernel.registration()` for its activation binding.
Each mounted method dispatches browser actions through its own scope; cleanup
removes that binding without changing other activations of the same recipe.
Verify direct calls, concurrent mounts and cleanup in `tests/core/test_tools.py`
and the action-pipeline tests in `tests/tools/execution/test_invocation.py`.

The remaining public SDK extension point is tracked in
[Harnessed #94](https://github.com/mathisarends/harnessed/issues/94): durable
plugin-owned state through a public service instead of the internal
`PluginInstructions` persistence dependency in `HumanHandoff`. That compatibility
code remains in place until a supported upstream API is available.

## Project status

The core is implemented and tested against real Chrome, including transformed,
nested, and out-of-process iframes (OOPIFs). Broader platform coverage,
perspective-transformed frames, and recovery from process crashes remain areas
for further validation.
