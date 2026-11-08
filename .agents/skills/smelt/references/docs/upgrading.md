# Upgrading Smelt

## 0.5.0 to 0.6.0

0.6.0 retains report schema 2, YAML version 1, grouped debt baseline version 2,
the default rule set and exit codes. No baseline rewrite is required. The six
new rules are opt-in. See the [changelog](../CHANGELOG.md#060---2026-11-08).

### Upgrade checklist

1. Update installation, dependency, hook and CI pins together:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.6.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.6.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.6.0]` for isolated Python hooks,
   `rev: v0.6.0` for source hooks and `uvx --from smelt-cli==0.6.0 smelt check`
   in CI. Run `prek install` after updating hooks. Source installs require
   Rust 1.88+ and a platform linker; wheels include the native client.

2. Refresh the editor schema with `smelt config schema > .smelt.schema.json`.
   Review `smelt config show --sources`, then run
   `smelt check --show-hints --fail-on warning` and the project's hooks and tests
   before relying on staged checks or updating accepted debt. Keep the reviewed
   configuration; `init --maintainability` is a starter, not a migration command.

3. Install the bundled agent skill with `smelt skill install`. To refresh an
   existing copy after upgrading, use `smelt skill install --force`; this replaces
   local edits and obsolete references. Preserve customizations first and use
   `--destination` for a custom skill location. See [CLI](cli.md#agent-skill).

4. Adopt the new reviews deliberately:

   | Rule | Activation | Review |
   | --- | --- | --- |
   | [SMT331](rules/SMT331.md) | `structure.file_naming.yaml_extension: yaml` (or `yml`) | Canonical YAML extensions |
   | [SMT332](rules/SMT332.md) | `structure.file_naming.compose_basename: compose` (or `docker-compose`) | Canonical Compose basenames |
   | [SMT333](rules/SMT333.md) | `rules: {prefer-callable-instance: hint}` | Single public instance method |
   | [SMT334](rules/SMT334.md) | `rules: {private-class-constant: warning}` | Private literal class constants |
   | [SMT335](rules/SMT335.md) | `rules: {internal-public-attribute: warning}` | Public data without external use |
   | [SMT336](rules/SMT336.md) | `rules: {redundant-module-name: hint}` | Module filenames repeating package context |

   Filename, symbol and placement repairs remain manual. Review imports,
   inheritance, framework contracts and consumers outside the analysis scope
   before renaming or moving code. Hidden YAML files and dotted Compose variants
   are included when file-naming policy is enabled; exclusions still apply.

### Information-hiding selection

Existing rule configurations keep their behavior. To adopt the complete policy,
replace the individual SMT316/SMT320/SMT335/SMT429/SMT430 entries with
`information-hiding: warning`, retaining any desired individual exceptions beside
it. If your previous selection omitted some members, adopting the group enables
them too. Public APIs used only by tests are included. Codes, inline suppressions
and debt fingerprints do not change; no baseline rewrite is required.

`smelt init --maintainability` writes this group in new configurations, which adds
SMT320 and SMT335 to its former review selection. Existing configurations are not
rewritten. Catalog/report rule metadata gains an additive `groups` list.
See [information-hiding scope and precedence](rule-selection.md#information-hiding).

## 0.4.0 to 0.5.0

0.5.0 retains report schema 2, YAML version 1, the default rule set and exit
codes. The eight new checks are opt-in. Debt baseline writes change format, and
SMT321 debt identities need review. See the
[changelog](../CHANGELOG.md#050---2026-11-02) for all release details.

### Upgrade checklist

1. Update local, hook and CI installations together before rewriting a baseline:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.5.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.5.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.5.0]` for isolated Python hooks,
   `rev: v0.5.0` for source hooks and `uvx --from smelt-cli==0.5.0 smelt check`
   in CI. Run `prek install` after updating hooks.

2. Refresh the editor schema with `smelt config schema > .smelt.schema.json`.
   Run `smelt check --show-hints --fail-on warning` and inspect stored debt with
   `smelt debt --show` before pruning or re-recording it. Review unscoped SMT321
   debt explicitly; pruning does not accept current findings.

3. Adopt new rules deliberately through `rules` or `--select`: [SMT324](rules/SMT324.md),
   [SMT326](rules/SMT326.md), [SMT327](rules/SMT327.md), [SMT328](rules/SMT328.md),
   [SMT329](rules/SMT329.md), [SMT330](rules/SMT330.md) and [SMT431](rules/SMT431.md).
   Activate [SMT325](rules/SMT325.md) with a package contract's
   `module_docstrings: require`. These new checks do not rewrite code.

### Grouped debt baselines

New `smelt debt` and `smelt debt --prune` writes use grouped JSON version 2;
version-1 files remain readable, but older Smelt versions cannot read version 2.
Pruning upgrades assessed debt without accepting new findings and retains debt
for inactive rules. Report JSON schema 2 and configuration version 1 stay unchanged.

SMT321 fingerprints now distinguish enclosing functions. Existing fingerprints
without that identity require review and explicit re-recording; `--prune` removes
them without accepting current findings. This prevents an old violation in one
function from hiding a newly introduced violation in another. Use `smelt debt
--show [PATHS]` to inspect stored debt without rewriting it. See
[adoption](adoption.md#grouped-baselines-and-inspection).

### Changes in findings

With `bundle_imports_at: 2`, [SMT108](rules/SMT108.md) now reviews mixed package
facade and implementation imports and includes missing export proposals. Bundling
advice is withheld when the proposed caller/facade edges close a known runtime
import cycle. Existing enabled policies can therefore produce different findings.

## 0.3.0 to 0.4.0

0.4.0 retains report schema 2, YAML version 1, the default rule set and exit
codes. SMT321, SMT322 and SMT323 are opt-in. Custom rule implementations need
the import migration below. See the
[changelog](../CHANGELOG.md#040---2026-11-01) for all release details.

### Upgrade checklist

1. Update installation, dependency, hook and CI pins together:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.4.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.4.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.4.0]` for isolated Python hooks,
   `rev: v0.4.0` for source hooks and `uvx --from smelt-cli==0.4.0 smelt check`
   in CI. Both published hooks now run on every commit, including policy-only
   changes. Keep `always_run: true` for local hooks, then run `prek install`.

2. Custom rule implementations must import and inherit `smelt.rules.base.Rule`
   instead of `BaseRule`. Annotations referring to the former structural `Rule`
   protocol must use `smelt.rules.base.RuleContract`. Stable SMT codes and
   diagnostic identities are unchanged.

3. Refresh the editor schema with `smelt config schema > .smelt.schema.json`.
   Review the effective policy with `smelt config show --sources`, then run
   `smelt check --show-hints --fail-on warning` before relying on staged checks
   or replacing accepted debt. Resolve any new SMT901 reports by using known
   SMT codes or prefixes in inline suppressions.

4. Adopt new capabilities deliberately: [shared configuration](configuration.md#shared-local-policy)
   uses `extends`; [SMT321](rules/SMT321.md), [SMT322](rules/SMT322.md) and
   [SMT323](rules/SMT323.md) require rule selection. SMT321 rewrites require both
   `--fix` and `--unsafe-fixes`; review intentional falsy defaults first. SMT322
   and SMT323 never rename symbols or rewrite navigation.

### Configuration filenames

`smelt init` now creates `smelt.yml`. Existing `smelt.yaml` files continue to
work, and `init --force` updates an existing file in place. If both filenames
exist in one directory, `smelt.yml` takes precedence; use `--config` to select
the other file explicitly. Cached and staged checks use the same preference.

### Changes in findings and review evidence

Report schema 2 and YAML version 1 are retained. Shared-helper grouping and
cycle/helper context add metadata without replacing individual findings. The
default cycle scopes and rule activation are unchanged. Unused new configuration
options do not change existing policy hashes.

Unknown inline suppression identifiers now produce SMT901 instead of silently
doing nothing. Inline comments use SMT codes/prefixes; YAML and CLI also accept
rule names. Existing recognized suppression identities are unchanged.

Literal lazy-export tables require a matching guarded `importlib` forwarding
handler. Supported `__all__` declarations are literal names or sorted/list/tuple
of that table. Arbitrary handler code, table mutation/escape, shadowed forwarding
operations and a `.pyi` export alone do not verify a runtime API. This evidence is
shared by visibility reviews, facade export review and canonical ownership.
This identifies symbol ownership; it does not infer dynamic import execution.
Layer/cycle analysis retains its existing explicit import graph, and SMT319
retains its direct static re-export requirement. Dynamic loading remains an
analysis limit; no new routing advice or architecture exemption is introduced.
See [configuration](configuration.md) for the optional ownership and cycle keys.

## 0.2.0 to 0.3.0

0.3.0 changes the JSON check-report contract. Existing YAML configurations keep
`version: 1`; the default rule set and exit codes are unchanged. SMT109 and SMT320
require deliberate adoption. Read the [changelog](../CHANGELOG.md#030---2026-11-01)
for the complete release details.

| What changed | What to do |
| --- | --- |
| JSON check and error documents use `schema_version: 2` | Update consumers before upgrading CI; see the example below. |
| JSON coverage is compact by default | Add `--show-coverage` if a consumer needs roots, policies, Python targets, ordering barriers or the per-file inventory. |
| Visibility boundaries are shared through `usage_scopes` | Resolve each finding's `expected.usage_scope_index` against the report-level array. |
| Text groups related ordering findings and omits empty details | Use JSON for structured consumers, or `--format concise` for one line per finding. |
| Existing checks recognize more evidence | Review the findings changes below before replacing accepted debt. |
| New facade and module-symbol reviews | Adopt their settings separately if useful; neither rewrites code. |

### Upgrade checklist

1. Update JSON consumers as described below, then update every installation pin
   together: project dependency and lockfile, isolated hook dependencies, Git hook
   tags and CI commands. For a tool installation:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.3.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.3.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.3.0]` for an isolated Python hook,
   `rev: v0.3.0` for a source hook, and
   `uvx --from smelt-cli==0.3.0 smelt check` in CI. Run `prek install` after updating
   hooks. See the complete [integration examples](integrations.md).

2. Refresh the local editor schema from the configuration directory:

   ```bash
   smelt config schema > .smelt.schema.json
   smelt config show
   ```

   Keep the reviewed YAML. `init --maintainability` is a starter for new configs;
   do not use `init --force` to migrate an existing policy.

3. Run a full review before relying on staged or changed-only results:

   ```bash
   smelt check --show-hints --fail-on warning
   smelt check --format json --show-coverage > smelt-report.json
   ```

   Exit `1` means findings meet the selected threshold; exit `2` means a usage,
   configuration or analysis error. Inspect these results before recording or
   pruning debt. Existing SMT codes and debt identities remain valid.

4. Stage the intended changes, run `smelt check --staged --fail-on warning`, then
   run the project's hooks and tests. Full CI checks still enforce the whole
   adopted policy.

Python 3.12+ remains required; use an interpreter that can parse your project's
syntax. Wheels include the native client for Linux x86_64/aarch64, Windows x86_64
and macOS x86_64/aarch64. Source installs, including Git-based hooks, require
Rust 1.88+ and a platform linker. This requirement was introduced in 0.2.0.

### JSON report consumers

Before, schema 1 embedded visibility boundaries in each finding:

```python
scope = finding["expected"].get("usage_scope")
```

Schema 2 stores each distinct boundary once. A consumer that supports both
released formats can normalize it as follows:

```python
def usage_scope(report, finding):
    version = report["schema_version"]
    if version not in (1, 2):
        raise ValueError(f"Unsupported Smelt report schema: {version}")
    expected = finding.get("expected") or {}
    if version == 1:
        return expected.get("usage_scope")
    index = expected.get("usage_scope_index")
    return None if index is None else report["usage_scopes"][index]
```

The index is zero-based; `0` is valid. The array is absent when there are no
usage scopes. Error documents also use schema 2 and retain `status: error` and
`error`; handle them before iterating findings. For coverage details, change:

```bash
smelt check --format json --show-coverage
```

`--show-coverage` restores the full coverage payload; it still emits schema 2 and
does not restore embedded usage scopes. JSON retains every ordering finding even
when text groups them. SARIF remains 2.1.0 and exposes shared visibility boundaries
under `runs[].properties.usageScopes`. Scope, comparison metadata, configuration
warnings and exit thresholds remain available. See [CLI and reports](cli.md).

### Adopt the new reviews

For a project with an `app.browser` package, merge these entries into the existing
configuration, adjusting the package name:

```yaml
rules:
  internal-public-module-symbol: warning  # SMT320

structure:
  contracts:
    browser-api:
      match: app.browser
      export_at: 3                       # SMT109; minimum 2 outside importers
      count_tests: false                 # true also counts discovered tests
```

[SMT109](rules/SMT109.md) reviews widely imported implementation names missing
from a package facade. Its default severity is `hint`, so use `--show-hints` to
see it. Review ownership and initialization before adding exports; a missing
cycle witness does not establish import safety.

[SMT320](rules/SMT320.md) reviews public uppercase module assignments and PEP 695
type aliases without observed external use or public-signature evidence. Exports,
analyzed callers and public annotations preserve names. Excluded and external
consumers remain unassessed. Review the API before renaming. See the full
[source conventions](structure.md) for both rules and their limits.

### Changes in findings under existing policies

- SMT313 can report ordering opportunities previously blocked by builtin unions
  such as `str | bytes` on declared Python 3.10+ targets. Defaults, unknown types
  and namespace mutations retain conservative barriers. Python 3.12/3.13 forward
  references can still require `from __future__ import annotations`.
- SMT424/SMT425/SMT426 follow one directly executed, unambiguous local helper,
  including awaited async helpers. Outcome recognition can remove a hint; an
  unbounded wait hidden in a helper can add one. Async caller deadlines do not
  bound synchronous subprocesses. Further calls and imported helper bodies
  remain outside inference.
- Visibility reviews preserve members of classes exported through static facades
  and re-export chains. SMT429 distinguishes test-only function references from
  helpers also used internally. Fewer hints do not establish that code is unused.
- Multiline suppression comments now follow their logical statement. Exceptions
  on individual imported names stay local; inspect changed suppression findings.
- Overlapping test roots use the most specific root. SMT108/SMT109 thresholds
  choose the most specific matching package pattern; equally specific conflicting
  settings are configuration errors. Consolidate those settings if needed.

## 0.1.x to 0.2.0 or later

Apply the [configuration migration table](configuration.md#breaking-change-migration)
first. Removed `review_*`, assertion/private-import switches, binary helper
conventions and `ordering.enabled` become errors. Enable fixed checks by name
under `rules`; ordering options alone do not enable SMT313. Configuration stays
`version: 1`, and stable SMT codes remain aliases.

Then apply the 0.3.0 report migration above. For upgrades from before 0.1.4, also
review the [activation changes](../CHANGELOG.md#014---2026-10-29): import cycles
and unclassified-module hints require explicit selection.
