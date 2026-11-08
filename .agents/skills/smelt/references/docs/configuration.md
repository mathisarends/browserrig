# Explicit rules and editor support

Use `smelt.yml` for project configuration; `smelt init` creates it by default.
Existing `smelt.yaml` files remain supported. When both filenames exist in the
same directory, Smelt selects `smelt.yml`; `--config` selects a file explicitly.

Configure a fixed check or coherent rule group once, by name. Its value enables it
and sets its severity. No separate `review_*` switch is needed.
The same names appear in YAML, CLI selection, `explain`, diagnostics and JSON.
Stable SMT codes remain valid aliases and keep existing debt identities.

## A small Python project

For a project containing `src/harnessed/` and `tests/`:

```yaml
# yaml-language-server: $schema=.smelt.schema.json
version: 1

project:
  root_packages: [harnessed]
  source_roots: [src]
  test_roots: [tests]

rules:
  public-definitions-first: error
  bundled-instance-assignment: error
  information-hiding: warning
  internal-static-helper: hint
  test-without-outcome-check: warning
  test-only-checks-possibly-empty-data: warning
  unbounded-test-wait: warning
  independent-test-case-loop: hint
  async-mock-without-await-check: warning
```

Generate this explicit starting selection with `smelt init --maintainability`.
The flag chooses what `init` writes; later checks read the configured entries.
`information-hiding` covers SMT316/SMT320/SMT335/SMT429/SMT430, including public APIs
used only by tests. Individual entries override a group in the same map regardless
of key order; closest-package overrides still win. Existing individual selections
remain supported. See [group scope and migration](rule-selection.md#information-hiding).
Plain `init` retains its conservative architecture starter. Neither command
overwrites an existing config without `--force`.

For a flat package, use `source_roots: ['.']`. Root packages can be omitted and
discovered from the source roots. Namespace packages and uv workspace roots are
supported; loose standalone scripts are outside package selection. Source rules
also work without tests. Test roots name the tests that provide review evidence.

Larger projects use the same rule map and add their `architecture` policies.
These conventions do not assign architecture roles: `--strict-coverage` separately
requires every discovered production source to have an architecture policy or a
reasoned exclusion.

## Shared local policy

Independent workspaces can share explicit policy through one local `extends`
file. Each workspace still has its own configuration and `--config` invocation:

```yaml
# smelt.base.yml (a policy fragment; no project selection is required here)
version: 1
rules:
  import-cycle: error
  unbounded-test-wait: warning
suppressions:
  require_reason: true
```

```yaml
# runtime/smelt.yml
extends: ../smelt.base.yml
project:
  source_roots: [src]
  test_roots: [tests]
  coverage: strict
architecture:
  features: {root: runtime_extension.features}
rules:
  unbounded-test-wait: error
```

Run `smelt check --config runtime/smelt.yml` from the repository root, or
`smelt check` from `runtime/`; both select the same project and paths.

- `extends` is one nonempty relative local file path, resolved from the file
  containing it. A base may extend another base, up to 32 files. Missing files,
  inheritance cycles, invalid YAML and duplicate YAML keys are configuration errors.
  There is no remote loading, multiple inheritance or automatic cascading discovery.
- Mappings merge recursively. Explicit child values win. Lists replace the entire
  inherited list, including `[]`; allowances, exclusions and ignores never append
  silently. An empty mapping leaves inherited keys in place. Scalars and `null`
  replace inherited values; the result must satisfy the field's type.
- Defaults, package discovery and cross-field validation run on the complete
  effective configuration. A fragment need not declare `project` or `version`,
  but the combined result must declare `version: 1` and `project`. The editor
  schema permits fragments; Smelt checks required fields after composition.
- **All project paths use the selected workspace's directory**, including inherited
  source/test roots, project exclusions, test globs, `ignore.paths` and `debt`.
  For example, inherited `source_roots: [src]` means `runtime/src` above, even if
  written in the repository-level base. Only the `extends` reference itself uses
  its declaring file as the anchor. Dotted module patterns are unchanged.
- Override rules with the same key spelling as the base. Using both a rule name
  and its SMT code in the effective map remains a duplicate-alias error.
  Unknown rules, invalid severities and strict-coverage restrictions still fail.

`smelt config show` prints the complete effective policy. Add `--sources` to wrap
it with `config`, `sources` (base first, workspace last) and `origins` (explicit
YAML key locations mapped to absolute declaring-file paths). This works with
`--format json` or the default YAML; defaults and discovered package names have
no explicit origin. Inherited validation errors include the declaring file.

Every check reloads policy inputs before analysis reuse. Staged checks read every
base from the captured Git index, never from unstaged working files; bases must
therefore be staged and inside the repository. Editing a base invalidates dependent
staged results, including when the workspace YAML itself is unchanged. `--changed`
and `--staged` continue comparing old and new source under the same effective
current/index policy. Run a full check to inventory findings after changing policy.
An explicit check path naming any loaded base widens that workspace's check to
the whole project. It does not automatically run other workspace configurations.
The maintainer evaluation runner records every policy input's SHA256 in
`config_inputs` and rejects a comparison if a base changes during evaluation.

## Options and package exceptions

API ownership can be stated separately from export-frequency review:

```yaml
structure:
  canonical_exports:
    app.error.types.FeatureError: app.FeatureError
  contracts:
    errors:
      match: app.error
      export_at: 3
```

Both names must resolve to the same analyzed symbol through bounded static
re-export chains. The target must actually be public, including `__all__` when
declared. Missing, conflicting and unverifiable ownership is a config error,
even when SMT109 is not selected. Without an ownership declaration, existing
SMT109 behavior is retained. Declaring one owner prevents duplicate facade advice
for that symbol; it does not make other internal aliases public or exempt imports
from layers, package-public contracts or cycle checks. No callers or exports are
rewritten. Review the existing export paths before adding another API declaration.

Cycle analysis can separately select exact module edges and annotation participation:

```yaml
architecture:
  imports:
    cycles: [modules]
    type_checking: include
    type_checking_cycles: ignore
```

This retains annotation imports in dependency-boundary checks while excluding
them from cycle graphs. Defaults remain `cycles: [features, layers, siblings]`
and `type_checking_cycles: include`; `include` respects the global `type_checking`
setting. Existing scopes aggregate architecture nodes and can form cycles without
a connected concrete module cycle. Runtime witness
edges mean outside `TYPE_CHECKING`, including deferred imports, and do not prove
eager import-time failure.

Fixed patterns need no additional policy. Real parameters stay with their concept:

```yaml
structure:
  contracts:
    ordering-options:
      match: harnessed
      ordering:
        constants_exempt: true
        fix: off
    supported-integrations:
      match: harnessed.integrations
      rules:
        information-hiding: off
        internal-static-helper: off
    strict-core:
      match: harnessed.core
      rules:
        information-hiding: error

tests:
  assertion_helpers: [tests.assertions.assert_response]
  timeout_helpers: [tests.timing.deadline]
  quality_exclude: ['tests/generated/**']
```

`ordering` contains options, not activation. Enable `public-definitions-first` in
`rules`; public must precede private in any customized module/class category list.
Dependencies and execution barriers still take precedence over category order.
`fix: off` disables ordering writes; plain checks are always read-only.

Package `rules` use the same names, groups, codes and values as the project map. They apply
to findings originating in production modules of the matching package, including
test-only API findings located in production code. The closest enclosing package
entry wins for each rule. It can change severity, disable a global check, or
enable it only in that package. Conflicting settings for the same concrete package
and duplicate name/code entries are config errors. Package rule settings cannot
disable strict coverage. Test-file and project rules are rejected in package
overrides; use reasoned `ignore.paths` for exceptions in test files. Rule metadata
exposes `scope` as `source`, `test` or `project`, and package completions show
only applicable source rules.

Architecture/interface policies and parameterized conventions such as import
style, required modules, mirror layout, forbidden mock paths and patch limits
retain their policy activation. Declaring such a policy is enough to check it.
The catalog distinguishes those checks from explicitly selected fixed patterns.

```bash
smelt check --select internal-public-member,unbounded-test-wait
smelt check --select SMT3 --ignore internal-static-helper
smelt explain async-mock-without-await-check
smelt rules --format json
smelt config show
smelt context harnessed.core --format json
```

`--select` replaces normal selection. `off` settings and CLI ignores apply; a
closer package entry can deliberately re-enable a globally disabled rule.
`--ignore` excludes the rule across the run. Strict coverage remains mandatory.
`context` reports effective rule severities even for planned source files.
Turning a check off in a package does not report its old debt as fixed.

## Editor completion, hover and validation

`smelt init` writes `.smelt.schema.json` beside the config and adds the modeline
shown above. The schema is generated from the installed version's real rule
catalog. Hover content includes the precise pattern, a bad/good example, repair
advice and analysis limits. Completions show canonical problem names and allowed
severities; unknown names, old switches and invalid values are flagged.

The schema artifact has no effect on checking or activation. You can commit it
with the YAML for shared offline editing support, or ignore `.smelt.schema.json`
and regenerate it locally to keep generated hover content out of the repository.
After updating Smelt, refresh it from the config directory:

```bash
smelt config schema > .smelt.schema.json
```

For an existing YAML, export that file and add the modeline manually. Paths in the
modeline are relative to the config file. `init` refreshes its own generated schema;
it refuses to overwrite an unrelated file at that path. A custom `--config`
gets a schema beside that config, leaving reviewed configs elsewhere alone.

- **VS Code / Cursor:** install Red Hat's YAML extension. The modeline associates
  the schema with the file. Other YAML Language Server clients can use the same
  comment. See the [language server's schema association documentation](https://github.com/redhat-developer/yaml-language-server#associating-schemas).
- **PyCharm / IntelliJ:** select the local `.smelt.schema.json` using the schema
  switcher or **Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings**.
  See [YAML schemas in PyCharm](https://www.jetbrains.com/help/pycharm/yaml.html#json_schema).

The exported schema documents configuration shape. File existence, package
matches, aliases and architecture semantics are still validated by Smelt.

## Breaking-change migration

This section covers the 0.1.x to 0.2.0 configuration migration. For upgrading to
0.3.0, including JSON reports and installation pins, see [Upgrading Smelt](upgrading.md).

Removed switches are errors, not silent aliases. Move fixed-check activation to
the rule map; use `off` instead of a former `false`/`allow` exception. Existing
numeric codes keep their meanings. The configuration format remains `version: 1`.

| Removed setting | Explicit rule |
| --- | --- |
| `ordering.enabled` or an implicitly activating `ordering` object | `public-definitions-first` (SMT313) |
| `instance_assignments: separate` | `bundled-instance-assignment` (SMT314) |
| `member_visibility: private-when-internal` | `internal-public-member` (SMT316) |
| `static_methods: module-functions` | `internal-static-helper` (SMT317) |
| `tests.forbid_private_imports` | `private-test-access` (SMT420) |
| `tests.forbid_string_patch_targets` | `string-patch-target` (SMT422) |
| `tests.require_assertions` | `test-without-outcome-check` (SMT424) |
| `tests.require_non_vacuous_assertions` | `test-only-checks-possibly-empty-data` (SMT425) |
| `tests.review_test_deadlines` | `unbounded-test-wait` (SMT426) |
| `tests.review_case_loops` | `independent-test-case-loop` (SMT427) |
| `tests.review_async_mock_assertions` | `async-mock-without-await-check` (SMT428) |
| `tests.review_test_only_public_functions` | `test-only-public-function` (SMT429) |
| `tests.review_test_only_public_attributes` | `test-only-public-attribute` (SMT430) |

Former names `definition-order`, `prefer-private-module-function`,
`missing-test-assertion`, `vacuous-test-outcome`, `test-deadline`,
`independent-test-cases` and `async-mock-call-only` are replaced by the canonical
names above, consistently in rule configuration, `explain`, findings and reports.
The experimental `preset` field and `init --preset` are removed. Public Python rule
classes also use these concepts, such as `PublicDefinitionsFirst`,
`TestWithoutOutcomeCheck` and `AsyncMockWithoutAwaitCheck`.
The enriched Python schema entry point is
`smelt.engine.schema.config_json_schema()`; the config-model layer no longer
exports a catalog-aware schema function.

Visibility and test-quality checks remain static review aids. A public helper
without observed external use can still be a supported external API. Preserve
intentional exports and review callers before renaming; Smelt does not rename
APIs or extract helpers automatically. A clean check does not prove test quality.
