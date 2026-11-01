# Development

[Back to README](../README.md)

## Development

Development tools require Python >=3.12, uv, Node.js >=24, and pnpm 12.14.0.
Python sources live in `browserrig/`.

Keep public entry points before private helpers in modules, and public methods before
private methods in classes. Imports and prerequisite type or constant declarations come
first; preserve definition-time dependencies used by defaults, decorators and registries.
Apply this order to production code, tests and examples.

```powershell
uv sync --locked --extra openai
pnpm.cmd install --frozen-lockfile
uv run prek install --overwrite
uv run prek run --all-files

uv run ruff check browserrig examples tests
uv run ruff format --check browserrig examples tests
uv run pylint browserrig examples tests
uv run ty check
pnpm.cmd run lint
pnpm.cmd run format:check
uv run pytest                  # unit tests only (default)
uv run pytest -m integration   # real Chrome; `-m ""` runs everything
uv build
```

prek hooks use the uv and pnpm dependencies pinned in the lockfiles.
The existing `.pre-commit-config.yml` configures the checks; `--overwrite` replaces
any previously installed pre-commit hook.
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

## Harnessed compatibility

The opt-in `Done` plugin uses native hooks for continuation and tool execution.
Harnessed 0.8.0 has no output-policy hook, so `browserrig/completion.py` contains
one reversible, per-session bridge around the step runner's output handler. This
defers the declared output contract until finalization without changing the model
or session APIs. When upgrading Harnessed, verify that bridge with
`tests/test_completion.py`, including native/tool structured output, retries,
limits, streaming, and runtime removal.

## Project status

The core is implemented and tested against real Chrome, including transformed,
nested, and out-of-process iframes (OOPIFs). Broader platform coverage,
perspective-transformed frames, and recovery from process crashes remain areas
for further validation.
