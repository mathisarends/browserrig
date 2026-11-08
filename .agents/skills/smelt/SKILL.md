---
name: smelt
description: Configure and use Smelt to check Python architecture, package APIs, source conventions and test quality. Use for smelt.yml policies, SMT findings, changed or staged checks, debt baselines and Smelt hook/CI integration.
---

# Use Smelt

Smelt is a static Python guardrail tool. Follow the project's existing policy and
use findings as evidence for a repair; advisory findings still require judgment.
This official skill and its offline manual ship with `smelt-cli`. `VERSION` in an
installed skill records the CLI version that installed it.

## Work in the actual project

1. Read project instructions, dependency pins and `smelt.yml` (or `smelt.yaml`).
   Use the project's command runner: examples below use `smelt`; a project-local
   dependency commonly uses `uv run smelt`. Check `smelt --version` against
   `VERSION`. After upgrading Smelt, refresh with `smelt skill install --force`
   using the same `--destination` if installed outside the default directory.
2. Before creating or moving code, run `smelt context <feature-or-module-or-path>`.
   For inherited policy, inspect `smelt config show --sources --format json`.
   A planned path is valid for `context`; explicit `check` paths must already exist.
3. After editing, run `smelt check --changed --fail-on warning --format json`.
   Read the evidence, use `smelt explain <code-or-name>` and fix the underlying
   behavior or dependency. Run relevant tests and the project's other checks too.
4. For branch review use `--changed --base origin/main` (or the actual base).
   For the commit use `smelt check --staged --fail-on warning`; this reads the Git
   index, including partially staged files and policy, rather than the working tree.
   Run a full `smelt check --fail-on warning` after policy changes and for CI.

## Policy and repair rules

- Most checks are opt-in. Fixed patterns use `rules: {rule-name: severity}`.
  `rules: {information-hiding: warning}` selects SMT316/SMT320/SMT335/SMT429/SMT430,
  including public APIs used only by tests. Individual entries override a group
  in the same map; closer package entries still win. Inspect the exact membership
  with `smelt explain information-hiding`. Existing individual settings remain valid.
  Architecture/package/test policies activate their associated rules. Use
  `smelt rules --format json` for the installed catalog and activation metadata.
  Do not assume a clean run means every rule or every source file was checked.
- `--select` replaces normal selection; names, groups, SMT prefixes and `ALL` are accepted.
  Explicit `off`, closest-package overrides and CLI ignores retain their semantics.
  Strict coverage cannot be bypassed with selection or lower severities. Choose
  policy for the project's intended boundaries; do not enable ALL as a default.
- Normal checks are read-only. `--fix` writes permitted source-ordering repairs;
  behavior-changing SMT321 repairs also need `--unsafe-fixes` and review of falsy
  values. `--unsafe-fixes` alone writes nothing. `--staged` rejects `--fix`.
- Do not disable checks, broaden exclusions or record debt merely to pass a check.
  When intentionally adopting a baseline, `smelt debt` records current findings
  and changes configuration. `smelt debt --prune` removes resolved debt without
  accepting new findings; `smelt debt --show` inspects stored debt read-only.
- For an intentional local exception, use a specific code and reason, for example
  `# smelt: ignore[SMT101] -- migration tracked in #123`. Statement comments do not
  suppress a whole function body. Keep exceptions narrow and address unused ones.
- Exit codes are `0` for passing, `1` for findings at the failure threshold, `2`
  for usage/configuration/analysis errors. Hints do not fail a check. JSON check
  reports use schema 2; inspect scope, comparison and coverage before interpreting
  `passed`. Changed/staged checks report new findings under current/index policy,
  including effects elsewhere; they do not inventory all existing violations.
- Smelt never replaces tests, Ruff or a type checker. It analyzes source statically;
  use a Python interpreter that can parse the project. Read each rule's inference
  limits before changing a public API or deciding a finding is a false positive.

## Read the relevant offline reference

The following files are copied/generated from the release's official documentation.
Load only the guide and individual rule pages needed for the task.
In the Smelt source checkout, edit rule metadata or original guides and run
`uv run python scripts/generate.py`, then `uv run python scripts/generate.py --check`.
Never hand-edit the generated rule pages or this skill's `references/`.
Installed consumer copies refresh through `smelt skill install --force`.

| Task | Reference |
| --- | --- |
| Install Smelt or start a policy | [Quick start](references/README.md) |
| Find commands, flags, outputs and scope semantics | [CLI and reports](references/docs/cli.md); also `smelt <command> --help` |
| Select rules and understand precedence | [Activation](references/docs/rule-selection.md) |
| Look up every rule, its rationale, examples, repair and config | [Complete catalog](references/docs/rules/README.md); follow its SMT page links |
| Configure roots, inheritance, overrides or editor completion | [Configuration](references/docs/configuration.md); `smelt config schema` prints the complete editor schema |
| Design features, layers, dependencies and coverage | [Architecture](references/docs/architecture.md) |
| Configure package APIs, visibility and source style | [Structure](references/docs/structure.md) |
| Configure test layout, mocks and test-quality checks | [Testing](references/docs/testing.md) |
| Adopt a baseline or reasoned exception | [Debt and suppression](references/docs/adoption.md) |
| Set up hooks, agents or CI | [Integrations](references/docs/integrations.md) |
| Upgrade or interpret changed behavior | [Upgrade guide](references/docs/upgrading.md), [changelog](references/CHANGELOG.md) |

For first-time installation use `uv tool install smelt-cli`, then
`smelt skill install` in the target project. Only run `smelt init` (or
`smelt init --maintainability`) when a new policy is needed; review the inferred
configuration. `init --force` overwrites policy. An installed skill is replaced
only on an explicit `skill install --force`, including local edits and obsolete
references. Put project-specific instructions outside the installed skill.
