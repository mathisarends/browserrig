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
uv sync --locked --extra openai
pnpm.cmd install --frozen-lockfile
uv run prek install --overwrite
uv run prek run --all-files

uv run ruff check browserrig examples tests
uv run ruff format --check browserrig examples tests
uv run pylint browserrig examples tests
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
Smelt is pinned to 0.5.0 through the same Python lockfile for local checks, hooks
and CI. Its hook runs on every commit, including configuration-only changes.
The checked-in `.smelt.schema.json` supplies offline editor validation for
`smelt.yml`; refresh it with `uv run --locked smelt config schema > .smelt.schema.json`
when upgrading Smelt.

The adopted rules review explicit `None` defaults, caller-before-helper order,
enum discriminator tags, class names, secret settings fields, module exports and
deterministic test inputs. `browserrig.kinds` retains a reasoned export exception
for its public compatibility facade. Module docstrings remain optional.
Inspect accepted findings with `uv run --locked smelt debt --show`.
After fixing findings, `uv run --locked smelt debt --prune` removes resolved entries
without accepting new debt. The grouped version-2 baseline requires Smelt 0.5.0;
its nine existing accepted occurrences are preserved by this migration.
On Linux and macOS, use `pnpm` instead of `pnpm.cmd` and `cp .env.example .env`
instead of `Copy-Item`.

JavaScript is checked with ESLint and Prettier: braces for every control block,
at most two nested blocks, and no nested ternary expressions. Pylint limits Python
blocks to three nesting levels; Ruff also checks for simplifications. CI runs the
same lint, formatting, and type checks. To format code, run
`uv run ruff format browserrig examples tests` and `pnpm.cmd run format`.

Integration tests require Chrome or Chromium. Set `BROWSERRIG_CHROME` or
`Launch(executable=...)` to select the executable. Media validation also
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
   the release date. The initial `0.1.0` metadata and notes are already present.
2. Once `main` is green, manually publish a GitHub release with a matching tag,
   such as `v0.1.0`, targeting the prepared commit on `main`. Alternatively, push
   that tag yourself: `git tag v0.1.0 <commit>` and `git push origin v0.1.0`.
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

The opt-in `Done` plugin uses native hooks for continuation and tool execution.
Harnessed 0.11.0 has no output-policy hook, so `browserrig/completion.py` contains
one reversible, per-session bridge around the step runner's output handler. This
defers the declared output contract until finalization without changing the model
or session APIs. When upgrading Harnessed, verify that bridge with
`tests/test_completion.py`, including native/tool structured output, retries,
limits, streaming, and runtime removal.
`tests/test_session_store.py` also checks reopening a paused `Done` turn with
`restore_outputs`, retained image assets and Browserrig's custom durable events.

## Project status

The core is implemented and tested against real Chrome, including transformed,
nested, and out-of-process iframes (OOPIFs). Broader platform coverage,
perspective-transformed frames, and recovery from process crashes remain areas
for further validation.
