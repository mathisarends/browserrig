# smelt

**A linter for Python architecture boundaries and code smells.**

If the same feedback keeps coming up in code review, make it a rule. Smelt puts
those decisions in `smelt.yml`, where coding agents can read them, check their
changes and fix findings before opening a PR. Commit hooks and CI enforce the
same policy.

Keep database imports out of application code. Keep package internals behind
their public API. Catch truthiness fallbacks that discard valid values, or tests
that wait without a timeout. Choose the checks that match your project from the
[rule catalog](docs/rules/README.md), or [add a rule](https://github.com/mathisarends/smelt/blob/main/CONTRIBUTING.md) for a
recurring pattern.

## Get started

Requires Python 3.12+. Install **`smelt-cli`** from PyPI:

```bash
uv tool install smelt-cli
smelt init --maintainability
```

Upgrading to 0.8.0? Follow the [upgrade checklist](docs/upgrading.md#070-to-080)
for pins and the new opt-in reviews.

Review the generated `smelt.yml`: it proposes a starting policy from your layout
and selects source and test checks. You decide which conventions to adopt.
Small libraries can use individual rules without declaring layers or features.

## Turn review feedback into policy

For a project with `src/app/` and `tests/`, this policy encodes two recurring
review comments: application code must not depend on infrastructure, and optional
defaults should distinguish `None` from valid falsy values.

```yaml
# smelt.yml
version: 1

project:
  root_packages: [app]
  source_roots: [src]
  test_roots: [tests]

architecture:
  layers:
    domain: {path: domain, may_depend_on: []}
    application: {path: application, may_depend_on: [domain]}
    infrastructure: {path: infrastructure, may_depend_on: [domain, application]}

rules:
  information-hiding: warning
  implicit-optional-default: warning
  unbounded-test-wait: warning
```

Smelt catches an import that crosses the declared boundary:

```python
# src/app/application/orders.py
from app.infrastructure.database import SqlOrderRepository  # SMT101
```

Application code should depend on an interface in an allowed layer; wire the
concrete repository in your composition root. Smelt also flags this fallback:

```python
def page_size(limit: int | None = None) -> int:
    return limit or 100  # SMT321: also replaces an explicit 0
```

If only `None` means "not supplied", use
`limit if limit is not None else 100`. If treating zero as missing is deliberate,
keep it with a reasoned exception.

```bash
smelt check --show-hints --fail-on warning
smelt explain SMT101  # why it fired and how to fix it
```

The same configuration can describe [feature boundaries and third-party dependencies](docs/architecture.md),
[package APIs and source conventions](docs/structure.md), and
[test conventions](docs/testing.md). Most checks require explicit selection or
an applicable policy; see [rule activation](docs/rule-selection.md).

Use `information-hiding` to review unnecessarily public functions, methods,
constants, type aliases and attributes together, including APIs used only by
tests. `smelt explain information-hiding` lists the five checks and their limits.
Individual rule settings can override the group.

## Catch it at commit time

Smelt uses the pre-commit hook format. With [prek](https://prek.j178.dev/installation/),
add this to `.pre-commit-config.yml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: smelt-staged
        name: smelt
        entry: smelt check --staged --fail-on warning
        language: python
        additional_dependencies: [smelt-cli==0.8.0]
        pass_filenames: false
        always_run: true
        require_serial: true
```

```bash
prek install
```

The hook installs a pinned wheel in its own environment and checks the Git index,
including partial staging, deletions and policy changes. New warnings and errors
block the commit. The agent gets a finding, fixes it, stages the change and retries.
Existing pre-commit setups can use the same configuration.

Use `smelt check --fail-on warning` in CI for the full project check. See
[integrations](docs/integrations.md) for GitHub Actions, source hooks and other
installation options. `prek run --all-files` runs the hook too, but the staged
hook still checks the index; use `smelt check` to review the working tree.

## Give agents a short feedback loop

Install the official Smelt skill in your project:

```bash
smelt skill install
```

Each `smelt-cli` release bundles the skill with its complete offline rule,
configuration and command reference. It installs in `.agents/skills/smelt`;
use `--destination <skill-directory>` for another location. After upgrading
Smelt, run `smelt skill install --force` to replace the previous skill and remove
obsolete references. Replacement includes local edits, so keep project-specific
instructions in `AGENTS.md` or `CLAUDE.md`. Installation works before `smelt init`
and leaves project policy unchanged. See [CLI and reports](docs/cli.md#agent-skill).

Add this to your `AGENTS.md` or `CLAUDE.md`:

```md
Before editing, run `smelt context <feature-or-path>` to read the applicable policy.
After editing, run `smelt check --changed --format concise` and address new findings.
Use `smelt explain <code>` for the rule's intent and repair advice.
Run focused tests, stage your changes, then run `prek run --all-files`.
Inspect and stage any hook fixes, and rerun until the checks pass.
Do not disable rules or record debt just to pass a check.
```

Findings include locations, evidence and repair advice. Changed checks compare
with `HEAD` by default; use `--changed --base origin/main` to review a branch.
For an existing codebase, [debt baselines](docs/adoption.md) let you adopt a policy
without requiring every old finding to be fixed in the first PR.

### Fast enough to run between edits

Local checks reuse a worker and cache analysis by content. Staged checks read Git
objects directly, including partially staged files, and reuse unchanged results.
An edit still checks its effects on other modules.

One documented benchmark used 250 modules with 12 methods each on Windows 11 /
Python 3.14. Warm medians, including process startup:

| Check | Unchanged retry | After a Python edit |
| --- | ---: | ---: |
| Staged CLI, transitive imports + member checks | 49 ms | 380 ms |
| Complete prek hook, member checks | 227 ms | 612 ms |

These are measured examples, not a latency guarantee. The first cache build took
about 2.6–3.9 seconds in that run; installation and other hooks are excluded.
See the [setup, raw samples and reproduction commands](https://github.com/mathisarends/smelt/blob/main/docs/agent-workflow.md#native-git-retained-worker-state-and-bounded-failure-handling)
for the exact policies and timings.

## Learn more

- [Configuration](docs/configuration.md) and [rule catalog](docs/rules/README.md)
- [Upgrading](docs/upgrading.md) and [changelog](CHANGELOG.md)
- [Documentation index](https://github.com/mathisarends/smelt/blob/main/docs/README.md) and [contributing](https://github.com/mathisarends/smelt/blob/main/CONTRIBUTING.md)

Smelt analyzes Python source statically. Use it alongside tests, a type checker
and Ruff; advisory findings still need review. See [scope and limits](https://github.com/mathisarends/smelt/blob/main/docs/vision.md).
Run Smelt with a Python version that can parse your code. Release wheels include
the native client; building from source requires Rust 1.88+ and a platform linker.
