# Upgrading Smelt

## 0.12 to 0.13

0.13.0 changes configuration keys, rule names and uv workspace policy ownership.
YAML version 1, check report schema 2 and CLI exit codes carry forward. Existing
debt keeps its identity for rules that retain their SMT code.

### Upgrade checklist

1. **Migrate configuration.** Use the [key mapping](#split-style-from-package-architecture)
   in the root, every local `extends` base and each member file. Move
   project-wide conventions to `style`. Keep package-specific conventions
   and source rule settings under `style.overrides`. Move required/public modules
   and facade thresholds to `architecture.packages`.
2. **Review workspace ownership.** Keep `project.workspace: uv`, shared
   style and rules, graph options, canonical exports and `architecture.members`
   in the root. Move each member's feature, layer, package API and style
   override entries to that member's file. A member's `match` must start with
   one of its own top-level package names. Split a pattern such as `*.domain`
   into one entry per matching package, for example `api.domain` in the member
   that owns `api`. Copy any root layout that previously covered member
   packages into the members that still need it. A root project may continue to
   declare a layout for its own packages. Review cross-member allowances
   independently of local layers.
3. **Update rule selectors.** Use canonical `family/finding` names or stable
   SMT codes in root/member rules, style overrides, CI and hooks. Replace broad
   enabling selectors with individual entries. Use the
   [renames](#renamed-rules) and [merged codes](#merged-rules) below.
4. **Review activation and exceptions.** Source conventions tied to a rule now
   enable it where the option applies. Review the new findings from values such
   as `private_attribute_boundary`, `call_argument_kinds`, `str_enum_values`
   and the `max_*` limits. Explicit SMT345 and SMT110 use limits of 5 and 20
   where the project sets none. Give each member exception its justification
   with `{severity: ..., reason: ...}` or `{value: ..., reason: ...}`. Move any
   legacy `reasons` entries beside their corresponding values. Equally specific
   style overrides for the same package must agree on values they both set.
5. **Migrate suppressions and debt.** Update inline comments to the surviving
   SMT codes. For merged-code debt, run `smelt debt --prune`, review the
   findings under the surviving rules, then record the debt you intend to
   keep. Member debt files may take precedence over workspace root debt.
6. **Update report consumers.** JSON check findings and `smelt rules --format json`
   use canonical families and rule names. Merged checks may provide an
   `expected.kind`. `smelt config show --sources` exposes member settings under
   `workspace_members` alongside `config`. `smelt context TARGET --format json`
   includes `style` and `rule_details` for resolved values and reasons.
   Scripts parsing `--format concise` should account for the rule name between
   the SMT code and the message. Explicit `--statistics` includes hints even
   without `--show-hints`.
7. **Refresh tools and verify.** Update dependency, hook and CI pins together
   after migrating the policy.

   ```bash
   uv tool install --upgrade 'smelt-cli==0.13.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.13.0]` for isolated Python hooks,
   `rev: v0.13.0` for source hooks and `uvx --from smelt-cli==0.13.0 smelt check`
   in CI. Run `prek install` after updating hooks. Regenerate the editor schema
   with `smelt config schema > .smelt.schema.json` and refresh the installed skill
   with `smelt skill install --force`. Inspect a source or planned path with
   `smelt context`. Run a full `smelt check --fail-on warning` and review changes
   in behavior before using changed or staged comparisons.

A config error for a retired selector names its replacement, for example
`private-symbol-import` becomes `visibility/foreign-private-access` and
`SMT366` becomes SMT340 `complexity/inline-call-argument`.

### Split style from package architecture

Move project-wide conventions from `structure` to `style`. Split each old
`structure.contracts` entry according to which fields it sets. Keep the same
`match` in both new entries when one old contract supplied both kinds of policy.

```yaml
# 0.13 replacement for one mixed contract named "orders"
style:
  max_positional_parameters: 3
  overrides:
    orders:
      match: app.orders
      max_positional_parameters: 5
      rules: {visibility/internal-public-member: warning}
architecture:
  import_graph: {type_checking: include, transitive: true}
  packages:
    orders:
      match: app.orders
      public: ['.']
      required: [domain]
      min_imports_to_bundle: 3
      min_importers_to_export: 2
```

| Before | Use in 0.13 |
| --- | --- |
| `structure` project conventions | `style` |
| `structure.contracts.<name>` style options, rule settings and reasons | `style.overrides.<name>` |
| `structure.contracts.<name>` public, required and facade policy | `architecture.packages.<name>` |
| `structure.canonical_exports` | `architecture.canonical_exports` |
| `architecture.imports` | `architecture.import_graph` |
| `structure.imports` | `style.imports` |
| `bundle_imports_at` | `min_imports_to_bundle` |
| `export_at` | `min_importers_to_export` |
| `module_import_exempt` | `module_import_exemptions` |
| `tests.unmirrored` | `tests.mirror_exclude` |
| `tests.forbid_mocks_in` | `tests.forbidden_mock_paths` |

Threshold values migrate verbatim. A `max_*` option permits up to that number
and a `min_*` threshold starts reporting at that number. The facade bundle
threshold counts distinct import paths inside a package. The export threshold
counts external importing modules that use a symbol. `exclude` names paths
outside the selected check, and exemptions describe an exception within a rule.
Architecture uses `allow` and `deny` for access. Style uses `forbid` for syntax
conventions.

### Explicit rule activation

Replace the former `information-hiding` selector with SMT316, SMT320, SMT335,
SMT429 and SMT430 at the former severity. These five codes also form the
equivalent comma-separated CLI selection. The `visibility` family covers
additional rules. Use named entries from `smelt init --maintainability` or a
local `extends` file to replace the unreleased `smelt:recommended` preset.
Families and `ALL` in YAML can disable or cap active rules. Named `on` uses
the catalog severity.

### Renamed rules

The following reviews use more precise names. Their SMT codes still identify the
same checks and debt entries.

| Code | Previous name | Canonical name |
| --- | --- | --- |
| SMT108 | `package-import-fanout` | `imports/excess-package-imports` |
| SMT322 | `deep-object-navigation` | `complexity/excess-attribute-depth` |
| SMT349 | `stateful-dataclass` | `modeling/dataclass-field-mutation` |
| SMT359 | `nested-conditional-expression` | `complexity/forbidden-nested-conditional` |
| SMT363 | `complex-comprehension` | `complexity/excess-comprehension-loops` |
| SMT364 | `constructor-logic` | `complexity/excess-constructor-decisions` |

0.13 renames every rule to `family/finding` and merges seven pairs of rules. YAML
version 1, report schema 2, exit codes, the default rule set and every unmerged
SMT code stay the same. See the
[full rule-name mapping](../CHANGELOG.md#renamed-rules) in the changelog.

### Merged rules

| Retired | Use instead | Notes |
| --- | --- | --- |
| SMT325 | SMT309 `layout/module-docstring-convention` | `module_docstrings: require` and `forbid` both enable it. |
| SMT326 | SMT323 `modeling/forbidden-base-class-affix` | It reports both prefix and suffix. |
| SMT332 | SMT331 `layout/file-name-convention` | There is one finding per file. |
| SMT342 | SMT341 `modeling/str-enum-value-convention` | Set `style.str_enum_values: auto` if you used SMT341 for auto values. The default `explicit` matches the former SMT342. |
| SMT358 | SMT357 `modeling/implicit-duration-unit` | It also reports unitless duration names. |
| SMT365 | SMT339 `visibility/foreign-private-access` | It also reports private module symbols. |
| SMT366 | SMT340 `complexity/inline-call-argument` | Set `style.call_argument_kinds` to keep the former scope: `[await]` for SMT340 alone, `[comprehension, aggregate]` for SMT366 alone. |

The SMT326, SMT357/358 and SMT339/365 merges can report more findings when the
old config enabled only one half. Review them or narrow the scope wherever
the surviving rule offers an option.

## 0.11.1 to 0.12.0

0.12.0 retains report schema 2, YAML version 1, grouped debt baseline version 2,
the default rule set and exit codes. No baseline rewrite is required. The two
new reviews require explicit selection. See the
[changelog](../CHANGELOG.md#0120---2026-11-16).

### Upgrade checklist

1. Update installation, dependency, hook and CI pins together:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.12.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.12.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.12.0]` for isolated Python hooks,
   `rev: v0.12.0` for source hooks and `uvx --from smelt-cli==0.12.0 smelt check`
   in CI. Run `prek install` after updating hooks.

2. Refresh the editor schema with `smelt config schema > .smelt.schema.json`
   and the agent skill with `smelt skill install --force`. Preserve local skill
   edits first and retain `--destination` for a custom installation. Run
   `smelt check --show-hints --fail-on warning`, plus the project's tests and
   other checks, before relying on changed/staged comparisons.

3. Adopt the new reviews deliberately:

   | Rule | Activation | Review |
   | --- | --- | --- |
   | [SMT366](https://github.com/mathisarends/smelt/blob/v0.12.0/docs/rules/SMT366.md) | `rules: {comprehension-in-call-argument: hint}` | List, set and dict comprehensions passed directly to calls |
   | [SMT367](rules/SMT367.md) | `rules: {excess-private-definitions: hint}` | Modules above `structure.max_private_definitions` (default 12) |

   Repairs remain manual. SMT366 skips generator expressions and conditional
   or repeated expression contexts; preserve callable lookup and argument
   evaluation order when naming intermediate collections. SMT367 counts private
   top-level classes, functions and PEP 695 aliases, lists constants separately
   and does not infer cohesion or safe extraction. Closest-package limits,
   including zero, are supported; setting a threshold alone does not enable it.

## 0.11.0 to 0.11.1

0.11.1 retains report schema 2, YAML version 1, grouped debt baseline version 2,
the default rule set and exit codes. No baseline rewrite is required. Existing
package policies now also check discovered tests and `conftest.py`, including
configured test roots inside source packages. See the
[changelog](../CHANGELOG.md#0111---2026-11-16).

### Upgrade checklist

1. Update installation, dependency, hook and CI pins together:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.11.1'
   # or: python -m pip install --upgrade 'smelt-cli==0.11.1'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.11.1]` for isolated Python hooks,
   `rev: v0.11.1` for source hooks and `uvx --from smelt-cli==0.11.1 smelt check`
   in CI. Run `prek install` after updating hooks.

2. Refresh the editor schema with `smelt config schema > .smelt.schema.json`
   and the agent skill with `smelt skill install --force`. Preserve local skill
   edits first and retain `--destination` for a custom installation.

3. Run `smelt check --show-hints --fail-on warning`, plus the project's tests
   and other checks. Review previously missed test imports for public entry
   points (SMT107), configured bundling thresholds (SMT108), and existing package
   re-exports when SMT319 is enabled. Repair imports according to the existing
   package policy. No new setting or automatic rewrite is introduced; SMT109's
   `count_tests` opt-in remains unchanged.

## 0.10.0 to 0.11.0

0.11.0 retains report schema 2, YAML version 1, grouped debt baseline version 2,
the default rule set and exit codes. No baseline rewrite is required. The four
new rules require explicit selection or package policy. See the
[changelog](../CHANGELOG.md#0110---2026-11-16).

### Upgrade checklist

1. Update installation, dependency, hook and CI pins together:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.11.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.11.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.11.0]` for isolated Python hooks,
   `rev: v0.11.0` for source hooks and `uvx --from smelt-cli==0.11.0 smelt check`
   in CI. Run `prek install` after updating hooks.

2. Refresh the editor schema with `smelt config schema > .smelt.schema.json`
   and the agent skill with `smelt skill install --force`. Preserve local skill
   edits first and retain `--destination` for a custom installation. Run
   `smelt check --show-hints --fail-on warning`, plus the project's tests and
   other checks, before relying on changed/staged comparisons.

3. Adopt the new reviews deliberately:

   | Rule | Activation | Review |
   | --- | --- | --- |
   | [SMT110](rules/SMT110.md) | `structure.max_module_imports: 10` | Distinct direct imports across project packages; choose a threshold for your project |
   | [SMT363](rules/SMT363.md) | `rules: {complex-comprehension: hint}` | Excessive iteration clauses, conditional elements and compound filters |
   | [SMT364](rules/SMT364.md) | `rules: {constructor-logic: hint}` | Constructor decisions above `structure.max_constructor_decisions` (default 2) |
   | [SMT365](https://github.com/mathisarends/smelt/blob/v0.11.0/docs/rules/SMT365.md) | `rules: {cross-module-private-attribute: warning}` | Private member accesses through known project receivers owned by another module |

   Repairs remain manual. SMT110 exempts package initializers and declared
   composition roots by default; `module_import_exempt: []` includes them.
   SMT363 supports `structure.max_comprehension_loops`; preserve generator
   laziness when rewriting. SMT364 excludes nested helper bodies and supports
   a zero decision limit. SMT365 skips unknown receiver types and ambiguous
   inheritance; `structure.private_attribute_boundary: package` permits
   cooperation within the immediate package. Closest-package overrides apply.

## 0.9.0 to 0.10.0

0.10.0 retains report schema 2, YAML version 1, grouped debt baseline version 2,
the default rule set and exit codes. No baseline rewrite is required. The two
new rules require explicit selection. See the
[changelog](../CHANGELOG.md#0100---2026-11-16).

### Upgrade checklist

1. Update installation, dependency, hook and CI pins together:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.10.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.10.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.10.0]` for isolated Python hooks,
   `rev: v0.10.0` for source hooks and `uvx --from smelt-cli==0.10.0 smelt check`
   in CI. Run `prek install` after updating hooks.

2. Refresh the editor schema with `smelt config schema > .smelt.schema.json`
   and the agent skill with `smelt skill install --force`. Preserve local skill
   edits first and retain `--destination` for a custom installation. Run
   `smelt check --show-hints --fail-on warning`, plus the project's tests and
   other checks, before relying on changed/staged comparisons.

3. Adopt the new reviews deliberately:

   | Rule | Activation | Review |
   | --- | --- | --- |
   | [SMT361](rules/SMT361.md) | `rules: {parallel-record-fields: hint}` | Declared sequence fields of one instance paired with `zip` |
   | [SMT362](rules/SMT362.md) | `rules: {loop-invariant-collection: hint}` | Repeated membership-set comprehensions over proven immutable inputs in passive `for` loops |

   Repairs remain manual. Review whether parallel fields represent records or
   deliberate column storage before restructuring them. Preserve guards, empty
   loops and evaluation order when moving lookup collections. SMT362 initially
   recognizes tuple literals and explicit immutable tuple/frozen-record inputs
   using local standard-library dataclasses and plain field types; Pydantic
   snapshots and `Annotated` fields remain outside its inference limits.

## 0.8.0 to 0.9.0

0.9.0 retains report schema 2, YAML version 1, grouped debt baseline version 2,
the default rule set and exit codes. No baseline rewrite is required. The thirteen
new rules require explicit selection or package policy. See the
[changelog](../CHANGELOG.md#090---2026-11-16).

### Upgrade checklist

1. Update installation, dependency, hook and CI pins together:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.9.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.9.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.9.0]` for isolated Python hooks,
   `rev: v0.9.0` for source hooks and `uvx --from smelt-cli==0.9.0 smelt check`
   in CI. Run `prek install` after updating hooks.

2. Refresh the editor schema with `smelt config schema > .smelt.schema.json`
   and the agent skill with `smelt skill install --force`. Preserve local skill
   edits first and retain `--destination` for a custom installation. Run
   `smelt check --show-hints --fail-on warning`, plus the project's tests and
   other checks, before relying on changed/staged comparisons.

3. Adopt the new reviews deliberately:

   | Rule | Activation | Review |
   | --- | --- | --- |
   | [SMT348](rules/SMT348.md) | `rules: {missing-interface-docstring: hint}` | Abstract and Protocol method contracts without docstrings |
   | [SMT349](rules/SMT349.md) | `rules: {stateful-dataclass: hint}` | Dataclasses that mutate their fields after construction |
   | [SMT350](rules/SMT350.md) | `rules: {missing-broad-except-reason: hint}` | Broad exception handlers without an explanatory comment |
   | [SMT351](rules/SMT351.md) | `structure.contracts.<name>: {match: app, dataclass_options: [slots]}` | Dataclasses missing required `frozen`, `slots` or `kw_only` options |
   | [SMT352](rules/SMT352.md) | `rules: {duplicate-function: warning}` | Matching module-level function implementations within a root package |
   | [SMT353](rules/SMT353.md) | `structure.contracts.<name>: {match: app, bases: {pydantic.BaseModel: app.core.Options}}` | Direct inheritance from an outside base with a project replacement |
   | [SMT354](rules/SMT354.md) | `structure.contracts.<name>: {match: app, errors: {base: app.errors.AppError}}` | Builtin exceptions raised instead of the project hierarchy |
   | [SMT355](rules/SMT355.md) | `rules: {duplicate-class-name: warning}` | Public top-level class names repeated within a package |
   | [SMT356](rules/SMT356.md) | `rules: {duplicate-narrowing-assert: warning}` | Attribute narrowing assertions repeated across methods |
   | [SMT357](rules/SMT357.md) | `rules: {missing-duration-unit: warning}` | Numeric duration names without a unit suffix |
   | [SMT358](https://github.com/mathisarends/smelt/blob/v0.9.0/docs/rules/SMT358.md) | `rules: {prefer-named-duration: warning}` | Literal durations in supported sleep, timeout and clock expressions |
   | [SMT359](rules/SMT359.md) | `rules: {nested-conditional-expression: hint}` | Conditional expressions nested in result branches |
   | [SMT360](rules/SMT360.md) | `rules: {mutable-field-in-frozen-dataclass: warning}` | Mutable container fields on frozen dataclasses |

   Repairs remain manual. Preserve exception behavior and duration units when
   changing interfaces. Review ownership and caller aliases before replacing
   mutable containers: `Mapping` alone does not freeze a dictionary, and a
   mapping proxy needs a defensive copy to isolate it from the caller. Preserve
   lazy evaluation when expanding nested conditional expressions. Follow each
   rule's documented inference limits before treating a finding as a defect.

## 0.7.0 to 0.8.0

0.8.0 retains report schema 2, YAML version 1, grouped debt baseline version 2,
the default rule set and exit codes. No baseline rewrite is required. The five
new rules require explicit selection or package policy. See the
[changelog](../CHANGELOG.md#080---2026-11-14).

### Upgrade checklist

1. Update installation, dependency, hook and CI pins together:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.8.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.8.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.8.0]` for isolated Python hooks,
   `rev: v0.8.0` for source hooks and `uvx --from smelt-cli==0.8.0 smelt check`
   in CI. Run `prek install` after updating hooks.

2. Refresh the editor schema with `smelt config schema > .smelt.schema.json`
   and the agent skill with `smelt skill install --force`. Preserve local skill
   edits first and retain `--destination` for a custom installation. Run
   `smelt check --show-hints --fail-on warning`, plus the project's tests and
   other checks, before relying on changed/staged comparisons.

3. Adopt the new reviews deliberately:

   | Rule | Activation | Review |
   | --- | --- | --- |
   | [SMT343](rules/SMT343.md) | `rules: {redundant-private-delegate: hint}` | Methods that only forward unchanged arguments to an exclusive private helper |
   | [SMT344](rules/SMT344.md) | `rules: {redundant-name-alias: hint}` | Module aliases that only repeat a class or function name |
   | [SMT345](rules/SMT345.md) | `structure.contracts.<name>: {match: app, max_positional_parameters: 2}` | Parameters beyond the package limit must be keyword-only |
   | [SMT346](rules/SMT346.md) | `rules: {prefer-deferred-annotations: hint}` | Quoted annotations that can use deferred evaluation |
   | [SMT347](rules/SMT347.md) | `rules: {anonymous-tuple-type: hint}` | Fixed tuple types with repeated element types or at least three fields |

   Repairs remain manual. Update callers when making parameters keyword-only;
   preserve callbacks with externally defined positional signatures. Before
   removing aliases or delegates, review external consumers and framework hooks.
   When adding an annotations future import, verify runtime annotation consumers.
   A repeated tuple shape does not prove that two records describe one concept.

## 0.6.0 to 0.7.0

0.7.0 retains report schema 2, YAML version 1, grouped debt baseline version 2,
the default rule set and exit codes. No baseline rewrite is required. The six
new rules are opt-in. See the [changelog](../CHANGELOG.md#070---2026-11-14).

### Upgrade checklist

1. Update installation, dependency, hook and CI pins together:

   ```bash
   uv tool install --upgrade 'smelt-cli==0.7.0'
   # or: python -m pip install --upgrade 'smelt-cli==0.7.0'
   smelt --version
   ```

   Use `additional_dependencies: [smelt-cli==0.7.0]` for isolated Python hooks,
   `rev: v0.7.0` for source hooks and `uvx --from smelt-cli==0.7.0 smelt check`
   in CI. Run `prek install` after updating hooks.

2. Refresh the editor schema with `smelt config schema > .smelt.schema.json` and
   the agent skill with `smelt skill install --force` (preserve local edits
   first). Then run `smelt check --show-hints --fail-on warning`.

3. Adopt the new reviews deliberately:

   | Rule | Activation | Review |
   | --- | --- | --- |
   | [SMT337](rules/SMT337.md) | `rules: {deprecated-async-contextmanager-return: warning}` | `AsyncIterator` returns on `@asynccontextmanager` |
   | [SMT338](rules/SMT338.md) | `rules: {duplicate-literal-type: hint}` | Repeated multi-value `Literal` types |
   | [SMT339](rules/SMT339.md) | `rules: {private-symbol-import: warning}` | Production access to private project symbols |
   | [SMT340](rules/SMT340.md) | `rules: {await-in-call-argument: hint}` | Awaited results passed directly as arguments |
   | [SMT341](rules/SMT341.md) | `rules: {str-enum-auto-values: hint}` | `StrEnum` values via `auto()` |
   | [SMT342](https://github.com/mathisarends/smelt/blob/v0.7.0/docs/rules/SMT342.md) | `rules: {str-enum-explicit-values: hint}` | `StrEnum` values as explicit strings |

   SMT341 and SMT342 enforce opposite conventions; enable at most one. All
   repairs remain manual.

4. Scripts parsing text or concise output: details are now labelled by name
   (`Suggested name: _hits`) and repair advice shared by several findings of one
   rule is listed once under "Repairs shared by several findings". Prefer
   `--format json` for automation; it is unchanged.

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
   | [SMT332](https://github.com/mathisarends/smelt/blob/v0.6.0/docs/rules/SMT332.md) | `structure.file_naming.compose_basename: compose` (or `docker-compose`) | Canonical Compose basenames |
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
   [SMT326](https://github.com/mathisarends/smelt/blob/v0.5.0/docs/rules/SMT326.md), [SMT327](rules/SMT327.md), [SMT328](rules/SMT328.md),
   [SMT329](rules/SMT329.md), [SMT330](rules/SMT330.md) and [SMT431](rules/SMT431.md).
   Activate [SMT325](https://github.com/mathisarends/smelt/blob/v0.5.0/docs/rules/SMT325.md) with a package contract's
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
