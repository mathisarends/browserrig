# Development

[Back to README](../README.md)

Requires Python 3.12+, uv, Node.js 24+, pnpm 12.14.0 and Chrome/Chromium for
integration tests. On Linux/macOS, use `pnpm` instead of `pnpm.cmd`.

## Setup and checks

```powershell
uv sync --locked --extra openai --extra ocr
pnpm.cmd install --frozen-lockfile
uv run prek install --overwrite
uv run prek run --all-files
```

The hooks use pinned dependencies and the same checks as CI. Individual checks:

```powershell
uv run ruff check browserrig examples evals tests
uv run ruff format --check browserrig examples evals tests
uv run pylint browserrig examples evals tests
uv run ty check
uv run --locked smelt check --show-hints --fail-on warning
pnpm.cmd run lint
pnpm.cmd run format:check
uv run pytest
uv run pytest -m integration
uv build
uv run --no-sync python tests/check_distribution.py
```

Default pytest excludes Chrome integration tests; `-m ""` runs everything.
Set `BROWSERRIG_CHROME` to select Chrome. Media validation uses ffprobe when
available. The distribution check installs and imports the built wheel outside
the checkout and verifies JavaScript assets and typing data.

Format with `uv run ruff format browserrig examples evals tests` and
`pnpm.cmd run format`.

## Source conventions

Public entry points precede private helpers; within each visibility, callers
precede helpers when definition-time dependencies permit. Imports and prerequisite
types/constants come first. Apply this to production code, examples and tests.

Keep plugin configuration reusable and state activation-local. Declare lifetime
services with `needs`/`observes`; acquire resources in setup and register cleanup.
Compose capabilities in the application or a pack. See
[composition](browser-composition.md) and [AGENTS.md](../AGENTS.md) for tool guidance.

JavaScript requires braces, at most two nested blocks and no nested ternaries.
Python blocks are limited to three nesting levels. `smelt.yml` owns architecture
and source policies; accepted findings live in `.smelt/debt.json`.
`uv run --locked smelt debt --show` inspects them; `debt --prune` removes resolved
entries without accepting new debt. When upgrading Smelt, refresh its checked-in
schema and the skill under `.agents/skills/smelt`.

## Distribution and releases

Before publishing, run the checks and Chrome suite, update `CHANGELOG.md`, and
verify metadata/license in the built artifacts. The release workflow reruns CI,
requires a tag on `main`, checks matching versions, builds the wheel from the
sdist, and validates the exact artifacts uploaded to PyPI.

Configure the PyPI Trusted Publisher with:

| Setting | Value |
| --- | --- |
| Project | `browserrig` |
| GitHub owner/repository | `mathisarends/browserrig` |
| Workflow | `release.yml` |
| GitHub environment | `pypi` |

Create that repository environment and add reviewers if publication needs manual
approval. Trusted Publishing needs no API token. A manual **Actions → Release
package → Run workflow** run validates/uploads artifacts and skips publication.

To release:

1. Merge matching versions in `pyproject.toml`, `browserrig/__init__.py`, `uv.lock`
   and a dated changelog section.
2. Publish a matching GitHub release/tag on the prepared `main` commit, or push
   that version tag (for example `v0.2.0`). A tag push starts publication even if
   its GitHub release is a draft.
3. Watch the release workflow and approve the `pypi` environment if configured.

Branch pushes, PRs and manual workflow runs do not publish. Rerun failed workflows
rather than moving published tags; PyPI versions cannot be overwritten.

## Compatibility and coverage

Harnessed/provider extras are pinned to 0.16.0. State/checkpoint format 3 and audit
envelope 6 reject older data; keep old stores separate. Review the
[changelog](../CHANGELOG.md) when upgrading.

Persistence adapters in handoff/todos and compaction integration in task memory
include narrow internal Harnessed dependencies. Their restoration, request-context
and recovery tests matter when upgrading upstream.

CI covers Python 3.12–3.14 on Windows/Linux, with real Chrome tests on Linux.
macOS, perspective-transformed frames and browser-crash recovery remain coverage
or capability limitations.
