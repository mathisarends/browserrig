# Changelog

User-visible changes, newest first. Agents should read the latest release's
migration notes before interpreting fewer findings as an improvement. For the
current configuration and complete rule contracts, see the [README](README.md),
[rule catalog](docs/rules/README.md) and [activation guide](docs/rule-selection.md).

## [Unreleased]

## [0.8.0] - 2026-11-14

Report schema 2, YAML version 1, grouped debt baseline version 2, the default
rule set and exit codes remain unchanged. SMT343/SMT344/SMT346/SMT347 are opt-in;
SMT345 activates through an explicit package limit. All five reviews require
manual repairs. Update installation, hook and CI pins together to `0.8.0`
(`v0.8.0`), refresh the editor schema and reinstall the bundled agent skill with
`smelt skill install --force`. No baseline rewrite is required. See the
[upgrade checklist](docs/upgrading.md#070-to-080).

- Optional style review [SMT346](docs/rules/SMT346.md)
  `prefer-deferred-annotations` reports modules that quote annotations such as
  `list["Tab"]`. With the annotations future import or a declared Python 3.14+
  minimum the quotes are redundant; otherwise the hint suggests adding
  `from __future__ import annotations`. A `future_annotations: forbid` package
  contract keeps quotes before 3.14. `Literal` values, `Annotated` metadata,
  runtime strings such as `cast("Tab", ...)` and tests are ignored. Enable it
  with `rules: {prefer-deferred-annotations: hint}`; no automatic rewrite.
  Implements [#123](https://github.com/mathisarends/smelt/issues/123).

- Optional review [SMT347](docs/rules/SMT347.md) `anonymous-tuple-type`
  reports fixed-length tuple types in annotations and type aliases with three
  or more elements or a repeated element type, such as
  `dict[UUID, tuple[UUID, UUID, Connection]]`, and suggests a `NamedTuple` or
  frozen dataclass. `tuple[X, ...]`, two distinct element types, quoted
  annotations, dunder/`@override`/`@overload` signatures and tests are not
  reported. Enable it with `rules: {anonymous-tuple-type: hint}`; no automatic
  rewrite. Implements part of
  [#121](https://github.com/mathisarends/smelt/issues/121).

- Optional review [SMT344](docs/rules/SMT344.md) `redundant-name-alias` reports
  a module-level name that only repeats another class or function name, such as
  `AutofillData = PasswordData`, including `TypeAlias` and `type` statements.
  Unions, subscripts, `Annotated`, constants, conditional fallbacks, typing
  special forms and tests are not reported. Enable it with
  `rules: {redundant-name-alias: hint}`; no automatic rewrite. Implements
  [#120](https://github.com/mathisarends/smelt/issues/120).

- New package policy `max_positional_parameters` limits how many parameters a
  function or method may accept positionally; later parameters must be
  keyword-only. [SMT345](docs/rules/SMT345.md) `excess-positional-parameters`
  reports violations (warning). `self`/`cls`, `*args`/`**kwargs`, dunder,
  `@overload` and `@override` definitions and tests are not counted. Enable it
  with `structure.contracts.<name>: {match: app, max_positional_parameters: 2}`;
  `smelt context` shows the limit. No automatic rewrite. Implements
  [#122](https://github.com/mathisarends/smelt/issues/122).

- Optional review [SMT343](docs/rules/SMT343.md) `redundant-private-delegate`
  reports a method whose whole body returns a call to a private method of the
  same class that receives every parameter unchanged and is used nowhere else,
  such as `def events(...): return self._events(...)`. Validation before the
  call, shared or decorated helpers, dunder methods, classes with bases from
  other modules and tests are not reported. Enable it with
  `rules: {redundant-private-delegate: hint}`; no automatic rewrite. Implements
  [#119](https://github.com/mathisarends/smelt/issues/119).

## [0.7.0] - 2026-11-14

Report schema 2, YAML version 1, grouped debt baseline version 2, the default
rule set and exit codes remain unchanged. The six new rules SMT337–SMT342 are
opt-in; SMT341 and SMT342 are alternative `StrEnum` conventions, so enable at
most one. Text and concise output now label details by name and list shared
repair advice once; JSON, SARIF and GitHub output are unchanged. Update
installation, hook and CI pins together to `0.7.0` (`v0.7.0`), refresh the
editor schema and the installed agent skill. No baseline rewrite is required.
See the [upgrade checklist](docs/upgrading.md#060-to-070).

- Optional style rules fix how `StrEnum` values are declared.
  [SMT341](docs/rules/SMT341.md) `str-enum-auto-values` makes `auto()` the
  convention: it reports explicit strings equal to the lowercased member name,
  and `auto()` members in classes that need custom values such as
  `"mouseMoved"`. [SMT342](docs/rules/SMT342.md) `str-enum-explicit-values`
  makes explicit strings the convention and reports every `auto()` member.
  Enable one of them, e.g. `rules: {str-enum-auto-values: hint}`. Tests are not
  checked; no automatic rewrite. Implements
  [#116](https://github.com/mathisarends/smelt/issues/116).

- Repair hints of SMT316, SMT320, SMT335, SMT429 and SMT430 no longer repeat the
  member and its suggested name, which the message and the `suggested_name`
  detail already carry; they name the target only when a collision changes it.
  The hints are therefore shared across findings and listed once. Messages,
  finding ids and debt identities are unchanged.

- Text and concise output list repair advice repeated verbatim by several
  findings of one rule once, under "Repairs shared by several findings", instead
  of after every finding. Unique advice stays with its finding; JSON, SARIF and
  GitHub output still carry the hint on each finding.

- Text output labels finding details by name (`Suggested name: _hits`) instead
  of prefixing every detail with `Expected`, and omits the constant
  `automatic_rename` flag. JSON and SARIF are unchanged.

- Optional [SMT340](docs/rules/SMT340.md) reports an awaited result passed
  directly as a call argument, such as `Result(text=await client.read())`, and
  suggests naming it in a local variable first (the keyword for keyword
  arguments). Enable `rules: {await-in-call-argument: hint}`. Awaits in
  comprehensions, lambdas, conditional expressions, boolean operators and while
  conditions are skipped; tests are not checked; no automatic rewrite. Implements
  [#112](https://github.com/mathisarends/smelt/issues/112).

- Optional [SMT339](docs/rules/SMT339.md) reports production imports and
  module-qualified reads of private symbols defined in analyzed project modules.
  Enable `rules: {private-symbol-import: warning}`. Dunders, public aliases and
  initializer re-exports under public aliases stay valid; tests remain with
  SMT420. Respects the TYPE_CHECKING policy; renames stay manual. Implements
  [#105](https://github.com/mathisarends/smelt/issues/105).

- Optional [SMT338](docs/rules/SMT338.md), enabled with
  `rules: {duplicate-literal-type: hint}`, finds repeated multi-value `Literal`
  types within and across source files in the same root package. Findings group
  locations per file and value set, preserve `Annotated` metadata boundaries,
  and suggest a shared plain type alias. Facts are cached by file content;
  changes to existing groups remain visible in changed checks and debt baselines.
  Same values may describe independent concepts; no automatic rewrite is made.

- Optional [SMT337](docs/rules/SMT337.md) flags `AsyncIterator[T]` return
  annotations on `@asynccontextmanager` functions and recommends
  `AsyncGenerator[T, None]`. Enable
  `rules: {deprecated-async-contextmanager-return: warning}`. The decorator stays
  supported; ordinary async iterators are unaffected. Import aliases and quoted
  annotations are supported; rewrites remain manual.

## [0.6.0] - 2026-11-08

Report schema 2, YAML version 1, grouped debt baseline version 2 and the default
rule set remain unchanged. The six new rules SMT331–SMT336 are opt-in; canonical
filename checks activate through explicit file-naming policy. Existing individual
rule selections remain valid. New `init --maintainability` configurations select
`information-hiding`, adding SMT320 and SMT335 to the previous starter policy.
Update installation, hook and CI pins together to `0.6.0` (`v0.6.0`), refresh the
editor schema and review findings before changing debt. No baseline rewrite is
required for this upgrade. See the [upgrade checklist](docs/upgrading.md#050-to-060).

- Optional [SMT336](docs/rules/SMT336.md) reviews module filenames that repeat an
  ancestor package, such as `cars/application/car_exporter.py`. Enable
  `rules: {redundant-module-name: hint}`. Whole-name prefixes/suffixes and simple
  trailing-s plurals are recognized; occupied shorter names are not suggested.
  Renames and import updates remain manual. Implements
  [#94](https://github.com/mathisarends/smelt/issues/94).

- Enable the five public-API reviews together with
  `rules: {information-hiding: warning}` (SMT316/SMT320/SMT335/SMT429/SMT430).
  Tests alone do not justify public visibility. Individual entries override the
  group in the same map regardless of order; closer package settings still win.
  The group works with CLI selection/ignores and scoped ignores, and is exposed
  in `explain`, catalog JSON and the editor schema. Existing names, codes,
  suppressions and debt identities remain valid. `init --maintainability` now
  writes this group, adding the module-symbol and attribute reviews to its
  generated selection. See [scope and migration](docs/rule-selection.md#information-hiding).

- Optional [SMT335](docs/rules/SMT335.md) reviews public instance and class data
  attributes with no observed access outside their class. Enable
  `rules: {internal-public-attribute: warning}`. Test access preserves visibility
  without duplicating SMT430; exports and uncertain inheritance/framework
  contracts remain protected. Renames stay manual. Implements
  [#96](https://github.com/mathisarends/smelt/issues/96).

- Ship the official `smelt` agent skill with every wheel and source distribution,
  including the complete offline rule, configuration and CLI reference. Install
  with `smelt skill install`; refresh after upgrading with `--force`, which
  replaces local edits and obsolete references. Use `--destination` to choose
  another skill directory. See [agent skill installation](docs/cli.md#agent-skill).
  Generated references are checked for drift in CI and release validation with
  `python scripts/generate.py --check`. The bundle contains consumer guides and
  rule pages; benchmark/evaluation data and maintainer documents stay in the repo.

- Optional [SMT334](docs/rules/SMT334.md) reviews private literal constants such
  as `DownloadController._DOWNLOADABLE_EXTENSIONS` for placement at module scope.
  Enable `rules: {private-class-constant: error}` to block them. Inherited and
  decorated classes retain their attribute contracts; moves and reference updates
  remain manual. Implements [#82](https://github.com/mathisarends/smelt/issues/82).

- Optional [SMT333](docs/rules/SMT333.md), enabled with
  `rules: {prefer-callable-instance: hint}`, reviews classes with one public
  instance method for `__call__` and an operation-based class name. Findings keep
  constructor and call-time signatures separate. Existing callable APIs,
  inheritance and decorated/protocol classes remain valid; no automatic rename.

- Declare canonical YAML extensions and Compose basenames once with
  `structure.file_naming: {yaml_extension: yaml, compose_basename: compose}`.
  [SMT331](docs/rules/SMT331.md) and [SMT332](docs/rules/SMT332.md) flag other
  spellings throughout the project, including hidden configuration directories
  and dotted Compose variants. Policies are optional, respect exclusions and
  support staged checks; renames and reference updates remain manual.
  Staged checks reuse YAML candidates from native Git-index capture, with an
  independent flat-inventory fallback, instead of walking virtual directories.

## [0.5.0] - 2026-11-02

Report schema 2, YAML version 1 and the default rule set remain unchanged.
Debt writes now use grouped baseline version 2, which older Smelt versions cannot
read. Existing version-1 baselines remain readable; unscoped SMT321 debt needs
review and explicit re-recording. Update installation, hook and CI pins together
to `0.5.0` (`v0.5.0`) before rewriting baselines, and refresh the editor schema.
See the [upgrade checklist](docs/upgrading.md#040-to-050).

- Contributor checks now require an issue/ticket reference for TODO comments
  through Ruff TD003. Tracked TODOs remain allowed; Smelt's rule catalog is unchanged.

- Document SMT317's activation and developer-facing extraction evidence with
  concrete query-helper regressions. Inherited-class exclusions and the existing
  advisory behavior are preserved; no duplicate static-method rule is added.

- Optional SMT329 (`rules: {caller-before-callee: hint}`) reviews step-down reading
  order for direct same-visibility functions and ordinary methods. Recursive,
  shadowed and definition-time-dependent pairs are retained; SMT313's public-first
  categories take precedence. No definitions are moved automatically.

- Optional SMT328 (`rules: {redundant-dishka-provider: hint}`) reviews Dishka
  provider methods that only forward dependencies to a constructor. Findings
  include a direct registration candidate with recognized decorator options.
  Resource factories and additional logic remain valid; no automatic rewrite.

- Optional SMT327 (`rules: {secret-settings-field: warning}`) reviews secret-named
  Pydantic settings fields accepting plain `str`/`bytes`, including optional and
  annotated types. Correct secret types and nonsecret names remain valid.
  Findings omit default values; no annotations or consumers are rewritten.

- Optional SMT326 (`rules: {no-base-class-suffix: error}`) reviews class definitions
  such as `_MessageBase`. SMT323 retains its existing prefix semantics. Imports,
  aliases and test classes remain outside scope; no automatic rename.

- Optional SMT330 (`rules: {package-only-dunder-all: error}`) restricts module
  `__all__` declarations to package `__init__.py` files. Package overrides and
  reasoned suppressions retain deliberate compatibility exports; no automatic move.

- Optional SMT431 (`rules: {nondeterministic-test-data: warning}`) reviews known
  random/UUID data generators in tests and fixtures. Prefer fixed test inputs or
  seeded local generators; intentional randomness tests can retain reasoned
  suppressions. Production generators are unaffected; no automatic rewrite.

- SMT108 now reviews mixed package-facade and implementation imports with
  `bundle_imports_at: 2`, includes missing export proposals and blocks bundling
  advice when proposed caller/facade edges close a known runtime import cycle.

- Debt baselines now write grouped JSON version 2: repeated rule/path/message
  metadata appears once, while every accepted fingerprint and duplicate occurrence
  remains available for matching. Version-1 files remain readable; `smelt debt
  --prune` upgrades assessed entries without accepting new debt. Use `smelt debt
  --show [PATHS]` for a compact, read-only baseline summary, or add `--format json`
  for the grouped data. [SMT321](docs/rules/SMT321.md) now distinguishes enclosing
  functions in debt and changed checks, so fixing one function cannot silently
  accept an identical new violation in another. Old unscoped SMT321 debt requires
  review and explicit re-recording. See [adoption](docs/adoption.md).

- Package contracts now support `module_docstrings: require`, activating
  [SMT325](docs/rules/SMT325.md) `missing-module-docstring` for every analyzed
  production module, including empty package initializers. Empty/blank docstrings
  do not satisfy the requirement. Choose `forbid` for the existing
  [SMT309](docs/rules/SMT309.md) convention; use a reasoned file suppression or an
  explicit nested `allow` policy for exceptions. Defaults remain unchanged.

- Optional [SMT324](docs/rules/SMT324.md), enabled with
  `rules: {prefer-str-enum-discriminator: hint}`, reviews single-string `Literal`
  fields named `type`, `kind` or `tag` for shared `StrEnum` members. Keep narrow
  `Literal[EventType.MEMBER]` annotations and matching enum defaults. This syntax
  review does not prove union membership or rewrite code; Python targets before
  3.11 and general multi-value Literals remain unchanged.

## [0.4.0] - 2026-11-01

Report schema 2, YAML version 1 and the default rule set remain unchanged.
Custom rules must update `BaseRule` imports to `Rule` and annotations for the
former `Rule` protocol to `RuleContract`. Update installation, hook and CI pins
together to `0.4.0` (`v0.4.0`) and refresh the editor schema. See the
[upgrade checklist](docs/upgrading.md#030-to-040).

- Use `.yml` consistently in configuration examples, fixtures and maintainer
  scripts. `smelt init` now creates `smelt.yml`, which takes precedence when both
  supported filenames exist. Existing `smelt.yaml` files still work. The published
  `.pre-commit-hooks.yaml` manifest retains its required filename. Integration
  instructions consistently use prek.

- Optional [SMT323](docs/rules/SMT323.md), enabled with
  `rules: {no-base-class-prefix: error}`, rejects class definitions such as
  `BaseRepository` and `_BaseRepository` in favor of responsibility-based names.
  Imports, third-party inheritance, `Baseline` and `Base64` remain valid. Package
  rule overrides can disable the convention; checks never rename symbols.
  Smelt enables the convention for its own sources; the default set is unchanged.
- Smelt also enables the opt-in `deep-object-navigation` Law of Demeter review
  for its own sources. Facade analysis receives its file inventory directly,
  and filesystem/Python-target analysis receives its source store explicitly.
  SMT322 recognizes statically evidenced module/data namespaces and known value
  APIs, preserving unknown collaborator findings. Changes to imported record
  definitions are considered on every check; no code is executed or rewritten.
  Unproven namespaces remain advisory review candidates, with known receiver
  types and the unresolved step included for agent API-contract review. A finding
  alone does not require an architecture change.
- Rule implementations now inherit `smelt.rules.base.Rule` instead of `BaseRule`.
  The former structural `Rule` protocol is named `RuleContract`; lazy rule
  implementations retain the same interface. Update custom rule imports and
  type annotations accordingly.
- Independent workspaces can share a local policy fragment with `extends` and
  explicit child overrides. Mappings merge; lists replace, including `[]`.
  Project paths remain relative to the selected workspace. `config show --sources`
  explains effective inputs and origins; staged checks and cache dependencies
  include all bases. Both published hooks now run on every commit, including
  policy-only edits. See [shared configuration](docs/configuration.md#shared-local-policy).

- New opt-in [SMT322](docs/rules/SMT322.md) `deep-object-navigation` reviews
  method calls reached through multiple stored instance attributes, such as
  `self.browser.input.motor().aim()`. Enable with
  `rules: {deep-object-navigation: hint}` or `--select SMT322`; package rule
  overrides and inline suppressions preserve intentional navigation. Direct
  collaborator calls, pure data reads and direct-collaborator fluent chains
  remain quiet. This bounded syntax review has no automatic rewrite.
- [SMT901](docs/rules/SMT901.md) diagnoses unknown inline suppression identifiers,
  including readable rule names where stable SMT codes are required. Known
  inactive rules retain their narrowed-check behavior.
- [SMT426](docs/rules/SMT426.md) groups shared-helper operations by one repair in
  text and adds deterministic `shared_helper` JSON groups. Individual findings,
  identities, counts, suppressions and debt remain unchanged. [SMT424](docs/rules/SMT424.md)
  explains known helper inference limits at the affected call sites.
- [SMT104](docs/rules/SMT104.md) adds the opt-in `cycles: [modules]` scope and
  independent `type_checking_cycles: ignore`. Existing scopes are explicitly
  labeled as aggregated; witnesses include edge phases. Default scopes stay unchanged.
- [SMT109](docs/rules/SMT109.md) accepts optional, statically verified
  `structure.canonical_exports` ownership and distinguishes same-root/other-root
  importers. Existing exports inform the review; frequency alone never expands API.
- Literal lazy-export tables with a matching guarded `import_module`/`getattr`
  forwarder now contribute export identity and visibility evidence. Unsupported
  dynamic handlers, escaped/mutated tables and type stubs alone remain unverified.
- [SMT313](docs/rules/SMT313.md) permits bounded ordering fixes around unrelated
  nested-function dictionaries and `nonlocal` closure writes. Reflection on
  unknown receivers or ordered namespaces retains its manual-review barrier.

- New opt-in [SMT321](docs/rules/SMT321.md) `implicit-optional-default`
  reviews `parameter or fallback` for explicitly optional parameters with a
  `None` default. Enable with `rules: {implicit-optional-default: warning}` or
  `--select SMT321`. Use `--fix --unsafe-fixes` to replace it with an explicit
  `is not None` conditional after reviewing intentional falsy defaults. Plain
  `--fix` preserves existing truthiness behavior.

## [0.3.0] - 2026-11-01

### Upgrade first

**JSON consumers need an update.** Check and error documents now use schema 2.
Request `--show-coverage` for full coverage details and resolve
`expected.usage_scope_index` through the report's `usage_scopes` array. This is
a report-format change; YAML stays `version: 1`, and default rules, exit codes,
SMT codes and debt identities stay unchanged. See the
[upgrade checklist and compatible parser example](docs/upgrading.md).

Update tool, dependency, hook and CI pins together to `0.3.0` (Git tag `v0.3.0`),
then refresh `.smelt.schema.json`. Upgrading from 0.1.x also requires the
[configuration migration](docs/configuration.md#breaking-change-migration).

### New capabilities

| Capability | Enable / use | Details |
| --- | --- | --- |
| Review widely imported names missing from a package facade | Set a contract's `export_at` threshold; opt-in, hint severity | [SMT109](docs/rules/SMT109.md) |
| Review internal public constants and PEP 695 aliases | `rules: {internal-public-module-symbol: warning}`; opt-in | [SMT320](docs/rules/SMT320.md) |
| Get one-line findings with repair advice | `smelt check --format concise` | [CLI and reports](docs/cli.md) |
| Migrate existing installations and report consumers | Follow the release-specific checklist | [Upgrading](docs/upgrading.md) |

### Ordering and module visibility

- SMT313 now recognizes unions of unshadowed builtin types and `None` in eager
  function annotations for declared Python 3.10+ targets, so a helper annotated
  `str | bytes` no longer silently blocks public-first ordering on Python 3.12/3.13.
  Imported/user-defined operands, shadowed names, explicit namespace mutations and unions in defaults remain
  execution barriers. Inspect barriers with `check --format json --show-coverage`.
- New opt-in [SMT320](docs/rules/SMT320.md) `internal-public-module-symbol`
  reviews single, unconditional uppercase module assignments and PEP 695 type
  aliases with no observed external use or public-signature evidence. Enable it
  with `rules: {internal-public-module-symbol: warning}` or `--select SMT320`.
  Exports, imports/re-exports, test accesses, escaped modules and public annotation
  dependencies preserve names. Dynamic namespaces and uncertain bindings are
  skipped; external consumers remain unassessed. No automatic renaming.
- SMT311/SMT313 explanations clarify that Python 3.12/3.13 projects can retain
  an annotations future import for forward references in their chosen public-first
  order. Eager dependencies still take priority when the import is absent. `Self`
  requires a subclass-preserving return contract; no automatic replacement of a
  matching class-name annotation is suggested. See [definition ordering](docs/structure.md#definition-order-with-execution-dependencies).

### Test evidence and package contracts

- Opt-in SMT424/SMT425/SMT426 outcome and deadline reviews follow one direct call
  to an unambiguous, undecorated, non-generator helper in the same file, including local async
  helpers executed with `await` or `asyncio.run`. Assertions retain empty-loop
  review, and hidden unbounded operations report their helper and call site.
  Caller async deadlines guard async waits, never synchronous subprocesses.
  Uncalled definitions, unexecuted coroutines, callbacks, imported helper bodies
  and further helper calls remain outside inference; configured assertion helpers
  continue to work. No analyzed code is executed.
- Overlapping test roots consistently assign a test to the most specific declared
  root, independent of configuration order. Mirror checks retain separate
  workspace-member roots.
- Package contracts can set `export_at` for SMT109 `facade-export-gap`: one
  advisory finding per widely imported implementation name missing from its
  facade, with definition location, importer lists, other re-exports and a bounded
  cycle check. Tests count only with `count_tests: true`; type-checking-only
  imports and uncertain exports are skipped. No automatic API or import changes.
  See [facade reviews](docs/structure.md#suggestions-to-bundle-implementation-imports).
- Overlapping SMT108/SMT109 thresholds now choose the most specific pattern per
  concrete package, removing duplicate hints and allowing exact overrides of
  wildcard contracts. Equally specific conflicting settings are config errors.

### Reports, suppressions and fixes

- **JSON report schema 2:** `check --format json` emits a small coverage summary
  by default; `--show-coverage` restores full policy details and the per-file
  inventory. Repeated visibility boundaries move to report-level `usage_scopes`,
  referenced by each finding's `expected.usage_scope_index`. Scope, comparison,
  warnings and exit thresholds remain available. See [report compatibility](docs/cli.md).
- `check --format concise` prints one line per finding with repair advice.
  Text omits empty details, prints visibility limits once, and groups related
  late-import SMT313 findings with their affected lines. JSON keeps individual
  findings plus an `ordering` group; debt fingerprints are retained.
- Inline suppressions follow logical continuation lines, including interior
  comments in multiline assertions, formatted calls and signatures. Interior
  import-name exceptions stay local and never cover neighboring names, the next
  statement or a function body. Unused-suppression checks remain active. See
  [suppression scope](docs/adoption.md).
- Visibility rules preserve public members of classes exported through static
  package facades or `__all__`, including aliases and re-export chains; cache
  invalidation tracks export changes. SMT429 distinguishes functions referenced
  only by tests from helpers also used inside their module, without claiming
  unassessed external consumers do not exist.
- Cache directories ignore their own contents. Init reports the number of tests
  matching a mirror pattern, and ordinary text checks omit the policy coverage
  banner without architecture (strict coverage still applies). Hook documentation
  uses a pinned wheel installation and explains source-build requirements.
  SMT311/SMT318 explanations clarify decorated annotations and Literal-typed
  boundaries; SMT426's subprocess example explicitly sets `check=False`.
- Release checks enforce matching Python/native/lockfile versions, dated release
  notes and current installation pins. Publication also waits for installation
  smoke tests of the exact Linux x86_64, Windows x86_64 and macOS aarch64 wheels.

## [0.2.0] - 2026-10-31

- Visibility reviews (SMT316/SMT317/SMT429/SMT430) explicitly limit their claims to
  analyzed callers and expose `usage_scope`, including exclusions and unassessed
  maintainer scripts, unselected packages and external consumers. They do not
  scan excluded code or infer that unobserved callers cannot exist.
- SMT313 fix refusals identify the triggering expression and source location in
  `fix_blocker` and the human-readable reason, including inherited/decorated
  classes, namespace inspection and nonliteral type variables. Existing safety
  refusals are retained; skipped-fix output carries the same location.
- SMT425 recognizes locally assigned nonempty list/set/dict literals, including
  annotations and aliases, and discards that evidence after possible mutations,
  calls or branch merges. SMT424/SMT425 also recognize direct assertions in
  statically known, checked `sys.executable -c` subprocesses. Unchecked exits,
  optimized Python, dynamic scripts, files and potentially swallowed failures
  remain outside recognition; subprocess review hints explain that boundary.
- Smelt now checks its own sources with public-first ordering, internal-member
  visibility, test-only public API reviews, when-needed future annotations and
  test-quality reviews. CI and release validation fail on warnings too. Internal
  helpers are private, obsolete snapshot helpers are removed, and deliberate
  primitive/cache tests carry local, reasoned exceptions. Consumer defaults stay
  unchanged.
- SMT420 locates private imports on the imported name, including aliases in
  multiline imports. A reasoned exception on that name now survives Ruff
  formatting and does not suppress neighboring import lines; put multiline
  import exceptions next to the affected name.
- Optional [SMT319](docs/rules/SMT319.md), enabled with
  `rules: {prefer-package-import: hint}` or `--select SMT319`, suggests existing
  package re-exports so callers can combine imports through a common `__init__.py`.
  All names must have direct, unconditional public re-exports in analyzed code;
  internal package imports and unscanned third-party packages are excluded.
  Findings preserve aliases in their suggestions; checks never rewrite imports.
- Worker transport now acknowledges requests within 250 ms and bounds accepted
  responses to five seconds, including partial output. Failures fall back to
  foreground checking without repeating accepted requests. A watchdog and four
  OS-owned worker slots bound background sessions; terminated workers release
  capacity. Whole-process memory observations include helpers and Windows
  launchers; the retained-state budget is not a total-process memory quota.
- Default cached staged checks read HEAD, the index and Git objects through a
  persistent native reader, avoiding Git child-process starts. The reader supports
  SHA-1/SHA-256, packed objects, linked worktrees, split indexes and alternate
  commit indexes. Unsupported repositories, other Git overrides and reader
  failures fall back to Git; `--no-cache` keeps independent reads. Workers also
  retain bounded member dependency state, validating current inputs before reuse
  and discarding borrowed state on failed updates. Worker requests are sent as
  complete TCP frames. See the [paired CLI and complete-hook measurements](https://github.com/mathisarends/smelt/blob/main/docs/agent-workflow.md).
- Staged checks reuse verified policy blobs before parsing configuration, avoiding
  a redundant Git blob subprocess after source edits. Policy changes still use
  their captured object ID; `--no-cache` keeps independent reads. Paired Windows
  CLI edit medians improve about 11%; complete-hook gains remain inconclusive.
- The installed CLI now uses a native Rust client and bounded local workers for
  read-only checks. Fresh clients reuse imports, while every check captures current
  Git/config inputs. CI, fixes and other commands stay in the foreground; worker
  startup/transport failures fall back to checking. Workers restart when analyzer
  identity changes and expire after 120 idle seconds. Source installs, including
  pre-commit environments from Git, now require Rust; release wheels include the
  compiled client. `python -m smelt` retains the direct Python entry point.
- Member-local checks maintain a persistent reverse dependency index and replace
  only changed usage contributions. Unchanged decisions can be reused without
  loading all definition objects. Removed callers, re-exports, missing namespaces,
  inheritance and inventory changes remain part of invalidation.

- Checks select built-in rules using a generated lightweight catalog, loading only
  the needed implementations. Staged results can survive edits to unobserved
  content while preserving the current index hash in JSON/SARIF; additions,
  deletions, observed source, config, metadata and debt still invalidate them.
  Normal cached staged retries capture repository/HEAD and index in two Git
  invocations. A separate benchmark measures a retained Python worker including
  fresh client startup and IPC; it preceded the native client above.
  See [the performance measurements](https://github.com/mathisarends/smelt/blob/main/docs/agent-workflow.md).
- Staged checks read captured Git blobs directly instead of writing temporary
  source trees. An unchanged retry can reuse its exact result before loading the
  analysis engine. Per-file import, member and test facts and selected findings
  are reused across edits, with dependency-aware invalidation for callers,
  re-exports and fixtures. `--no-cache` remains an independent check. See the
  [paired CLI benchmarks and cache limits](https://github.com/mathisarends/smelt/blob/main/docs/agent-workflow.md).
- `architecture.imports.transitive: true` now checks arbitrary import chains for
  layer, cross-feature, shared, composition-root and third-party policies, e.g.
  `domain → shared.utils → sqlalchemy`. Findings include a deterministic shortest
  chain with each hop's source line; `TYPE_CHECKING` policy applies at every hop.
  The opt-in now follows all reachable module imports, including allowed layers
  and unused facade exports, rather than just selected re-exports. External
  packages remain leaves and the default is still direct imports only. Smelt's
  own repository policy enables these checks. See
  [SMT101](docs/rules/SMT101.md) and [SMT103](docs/rules/SMT103.md).
- **Breaking configuration API:** fixed source/test checks are enabled directly by
  problem name in `rules`, with one value for activation and severity. Removed
  `review_*`, assertion/private-import boolean flags, binary helper conventions,
  `ordering.enabled` and the experimental preset. Public-first ordering needs an
  explicit rule entry; options alone do not enable it. Package `rules` use the
  same names and closest-package precedence. Stable SMT codes, debt identities
  and architecture-policy activation are retained. See the complete
  [migration table and developer-facing YAML API](docs/configuration.md).
- `--select` and `--ignore` accept the same canonical names as YAML and `explain`.
  `context` reports effective rule severities for existing and planned modules.
  Scoped-off debt is retained as unassessed when recording/pruning.
- `smelt init --maintainability` writes explicit individual checks, plus a local
  `.smelt.schema.json` and YAML modeline. Editor completions, validation and hover
  examples come from the real catalog and work offline. Plain `init` keeps its
  conservative check selection. Existing configs can export `smelt config schema`
  and add the modeline; see [editor setup](docs/configuration.md#editor-completion-hover-and-validation).
- Optional [SMT430](docs/rules/SMT430.md), enabled by
  `rules: {test-only-public-attribute: warning}` or `--select SMT430`,
  reviews public instance/class data attributes read only by tests outside their
  class. Findings include test locations and a collision-free private name.
  Possible production accesses and uncertain class contracts preserve visibility;
  checks never rename code. Public-use rules now share the same member index,
  export/import evidence and private-name suggestions. The new rule is off by
  default and never renames code automatically.
- Optional [SMT318](docs/rules/SMT318.md), enabled with `rules: {SMT318: hint}`
  or `--select SMT318`, reviews direct `StrEnum.MEMBER.value` reads for using the
  string enum member directly. Known import aliases and analyzed re-exports are
  supported; ordinary enums, uncertain bindings and instance inference are
  excluded. Exact-string boundaries can still need a conversion, so findings
  remain advisory and checks stay read-only. The default rule set is unchanged.
- `smelt check --staged` reviews the actual Git index against HEAD, using staged
  source, configuration, Python metadata and debt. The new `smelt-staged` hook
  blocks new warnings as well as errors, including findings in unchanged methods
  whose last caller was removed. Partial staging and untracked files cannot hide
  commit findings. JSON/SARIF distinguish staged scope from working-tree changes.
- Content-addressed JSON caches reuse complete analyses, per-file member facts
  and the historical baseline. `--no-cache` recomputes independently. Member-use
  analysis avoids repeated per-function tree walks; cache invalidation includes
  contents, inventory, policy, Python targets and analyzer implementation. See
  [the commit workflow and benchmark](https://github.com/mathisarends/smelt/blob/main/docs/agent-workflow.md). Changed/staged
  snapshots reject symbolic links; staged fixes require editing and re-staging
  working files explicitly.
- SMT316 feedback explains how to retain a deliberate public API with a reasoned
  `# smelt: ignore[SMT316] -- ...` comment on its definition. Existing suppression
  reason and unused-suppression checks continue to apply with caching.

- Optional [SMT316](docs/rules/SMT316.md), enabled with
  `rules: {internal-public-member: warning}`, reviews public module functions and
  ordinary instance methods with no observed external use, including unused
  definitions. Findings suggest a private name and list internal uses/callbacks
  so agents can review renames. Existing private names are avoided. Explicit
  exports, decorators, inheritance and possible external method accesses preserve
  public APIs; test-only public module functions remain covered by SMT429.
- Optional [SMT317](docs/rules/SMT317.md), enabled with
  `rules: {internal-static-helper: hint}`, suggests extracting internal static helpers
  to private module functions. Class dependencies, inheritance, extra decorators
  and possible external callers preserve deliberate static APIs. Both new
  rules support closest package `off` overrides and appear in `smelt context`.
  Checks remain read-only and the default rule set is unchanged.
- Optional [SMT429](docs/rules/SMT429.md), enabled by
  `rules: {test-only-public-function: warning}`, reviews public module functions
  accessed from tests but not from other analyzed production modules. Findings
  suggest a leading underscore and include test locations so agents can review
  the rename and test the public caller. Explicit exports and decorated functions
  stay public; external/dynamic consumers remain a review limitation. The default
  rule set is unchanged.

## [0.1.6] - 2026-10-29

### Compatibility and activation

- SMT428 remains opt-in through `tests.review_async_mock_assertions`; the default
  rule set is unchanged. Its findings ask for review of an individual test, not a
  claim that the suite misses the regression.
- Existing `tests.review_test_deadlines` policies can now report additional known
  asyncio subprocess waits. Review each operation's local deadline, including
  cleanup paths, rather than adding a blanket timeout or await restriction.

### Added and fixed

- SMT426 now reviews `wait()` and `communicate()` on known asyncio subprocesses
  created through awaited standard factories or explicit Process annotations.
  Each operation needs its own local guard, including exit waits after bounded
  reads or `kill()`. Unknown process-like objects remain outside scope.
- Optional SMT428 (`tests.review_async_mock_assertions`) reviews call-only checks
  on known async mocks and async class-spec methods. Await assertions, deliberate
  scheduling checks and synchronous methods remain valid. Known fixture specs and
  simple local history values are traced without executing analyzed code; unknown
  methods and general data flow remain outside scope. Executed missing-await
  counterexamples demonstrate the distinction between call and await assertions.
- `context` text now shows all adopted test-quality review flags, including when
  only the newer policies are enabled.
- SMT424 recognizes awaited, typed Event observations inside local timeout
  contexts that raise on expiry, consistently with SMT426 deadline recognition.
  Unused contexts, unawaited waits and `move_on_after` scopes are not outcome
  evidence; configured timeout helpers alone still do not count as assertions.

## [0.1.5] - 2026-10-29

### Compatibility and activation

- Existing opted-in test policies can report additional MonkeyPatch operations
  and known instance accesses. New SMT425-SMT427 review policies remain opt-in;
  the small default rule set is unchanged. Review legitimate boundary tests
  rather than exposing internals or imposing a global mock ban.
- `--fail-on warning` now includes configuration warnings, and unused
  `pytest.raises`/`warns` context objects no longer count as outcome evidence.
  A passing static report is not proof of test effectiveness.

### Added and fixed

- `scripts/evaluate.py` supports repeatable agent review loops: compare two import
  roots on identical config bytes, retain
  structured recognition changes and independently bounded logs, then optionally
  execute explicitly selected pytest targets. Invalid analysis, timeouts and
  incomplete collection remain distinct from test failures; normal checks never
  execute analyzed tests. See the [evaluation workflow](docs/testing.md#evaluate-a-test-quality-change).
- Test outcome review now recognizes known mock interaction assertions, annotated
  fixture receivers and awaited, bounded asyncio Event observations. Unused
  `pytest.raises`/`warns` context objects no longer count as checks. Unknown
  `assert_*` methods and fixture execution alone remain insufficient evidence.
- [SMT420](docs/rules/SMT420.md) tracks direct known production constructors and
  explicitly typed instance reads, including analyzed facade re-exports and
  consistent known fixture return/yield tuple components. Unknown/conflicting
  outputs, private writes and local fakes are excluded; fixture inference has
  separate provenance and respects class/conftest scope. A private class import
  is not reported again for each public instance operation.
  [SMT421–SMT423](docs/rules/SMT422.md) now include MonkeyPatch attribute
  replacement, aliases and context scopes, with operation/provenance metadata.
  MonkeyPatch environment/mapping setup is excluded from the mock count.
- Optional [SMT425](docs/rules/SMT425.md), [SMT426](docs/rules/SMT426.md) and
  [SMT427](docs/rules/SMT427.md) review potentially vacuous outcomes, known waits
  without deadlines/scheduler-clock replacements, and small independent-case loop
  candidates. They remain advisory and require explicit test policies; no fixer,
  blanket mock/sleep ban or assertion quota is introduced.
- Configuration warnings now appear in JSON `configuration_diagnostics`, SARIF
  configuration notifications, GitHub annotations and text summaries. They count
  toward `summary.warnings` and `--fail-on warning`, including scoped/changed
  checks; rule selection, suppressions and debt cannot hide configuration warnings.

## [0.1.4] - 2026-10-29

### Migration: rule activation changed

- Only **SMT301, SMT901, SMT902 and SMT903** run by default. Declaring an
  architecture, package or test policy activates the corresponding checks without
  a second enable switch. The catalog now distinguishes 4 default, 24 policy-driven
  and 2 explicitly selected rules; activation and severity are separate.
- **SMT104 import cycles and SMT305 unclassified-module hints require explicit
  selection.** To retain these checks from earlier versions, add:

  ```yaml
  rules:
    SMT104: error
    SMT305: warning
  ```

- `--select SMT3` and `--select ALL` activate matching opt-in checks and replace
  normal selection. Explicit `off` settings and ignores still win; selection does
  not invent missing policies. Strict coverage remains mandatory when configured
  or requested, even outside the selected rule prefix.
- `smelt init` still proposes architecture but leaves naming conventions and test
  mirroring disabled for review. A detected mirror pattern remains available as a
  setting, with an activation comment.
- Debt for inactive or hint-only rules is retained when recording/pruning, rather
  than silently considered resolved. Older cycle and indirect-import debt can
  resurface because corrected fingerprints track the actual dependency. Review
  these findings before recording new debt.

### Added

| Capability | Rules / interface | What agents can now check |
| --- | --- | --- |
| Strict architecture coverage | [SMT306](docs/rules/SMT306.md), `project.coverage: strict`, `--strict-coverage` | Production files outside package selection, missing architecture roles and exclusions without reasons. These gaps cannot be hidden by changed/path filters, suppressions or debt. |
| Package structure and public APIs | [SMT107](docs/rules/SMT107.md), [SMT307](docs/rules/SMT307.md) | Required modules and explicit public entry points through `structure.contracts`; outside callers cannot import private implementation modules. |
| Import fanout | [SMT108](docs/rules/SMT108.md) | Optional hints when one outside caller imports too many distinct modules from the same contracted package. |
| Source conventions | [SMT308](docs/rules/SMT308.md)–[SMT312](docs/rules/SMT312.md) | Scoped absolute/relative import styles, module-docstring policy, future-annotation policy and private module/package names. Python targets come from declared metadata or configuration. |
| Definition order | [SMT313](docs/rules/SMT313.md) | Dependency-aware module/class ordering, including execution barriers and bounded, explicitly requested fixes. |
| Instance field assignments | [SMT314](docs/rules/SMT314.md) | Bundled or chained writes to multiple direct instance attributes when `instance_assignments: separate` is declared. |
| Type dispatch | [SMT315](docs/rules/SMT315.md) | Review hints for same-subject `isinstance`/`elif` chains under a declared `type_dispatch` policy. |
| Test quality | [SMT420](docs/rules/SMT420.md)–[SMT424](docs/rules/SMT424.md) | Configured private production access, forbidden mocks, string patch targets, per-test patch limits and missing recognized outcome assertions. |

- `smelt context <path> --format json` explains ownership, coverage status,
  applicable contracts, effective conventions and Python targets for existing or
  planned files. Planned placement is distinguished from analyzed source.
- `check --show-coverage` exposes the per-file policy inventory. JSON reports add
  discovery roots, classification counts, policy references, exclusions and a
  policy hash. Rule metadata exposes activation, analysis requirements and
  configuration paths through `rules`, `explain` and reports.
- Contributor documentation and catalog checks verify explicit registration,
  unique rule codes/names, complete metadata and generated documentation.
- Tag-triggered PyPI Trusted Publishing validates the tag/version and main
  ancestry, runs checks, builds and smoke-tests both distributions, then publishes
  the validated artifacts without a stored PyPI API token.

### Fixed

- Resolve named re-exports across layer, feature, shared and composition-root
  boundaries. Indirect findings retain the final forbidden target; declared
  feature wiring no longer produces false unknown-layer findings.
- Track every cyclic architecture edge and semantic identities/multiplicity in
  changed/debt comparisons. New edges, patches or ordering inversions cannot hide
  behind an accepted aggregate finding. Existing violations do not become new
  merely because an import's formatting, comment or alias changed.
- Merge namespace package portions, reject duplicate module definitions and infer
  usable workspace source roots. Grouped imports check every alias, and source
  discovery avoids symlink cycles.
- Reject duplicate YAML keys and invalid source encoding. With `--format json`,
  usage/configuration/analysis errors return structured error documents; reports
  identify their origin and comparison scope. SARIF and GitHub paths are rebased
  correctly for nested configurations.

### Agent workflow and limits

```bash
smelt rules --format json
smelt context path/to/module.py --format json
smelt check --changed --base origin/main --format json
smelt check --strict-coverage --show-coverage --format json
smelt explain SMT313 --format json
```

- Normal checks are read-only. After configuring ordering with `fix: safe-only`,
  `smelt check --select SMT313 --fix` can apply bounded definition moves. It
  preserves source trivia, validates the permitted AST moves and refuses unsafe
  or concurrently changed files. Run the project formatter afterwards.
- SMT314 and SMT315 have no automatic rewrite. Splitting assignments or converting
  type dispatch can change evaluation, guards and fallthrough.
- Coverage means policy assignment within declared discovery roots, not a proof
  of behavior. Package APIs and test-quality checks are static and do not infer
  dynamic imports, arbitrary runtime access or fixture dependency effects.
- Import fanout, match suggestions and missing-assertion checks are review aids;
  their default severities differ. Configure policy and severity deliberately.

[Unreleased]: https://github.com/mathisarends/smelt/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/mathisarends/smelt/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/mathisarends/smelt/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/mathisarends/smelt/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/mathisarends/smelt/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/mathisarends/smelt/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/mathisarends/smelt/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mathisarends/smelt/compare/v0.1.6...v0.2.0
[0.1.6]: https://github.com/mathisarends/smelt/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/mathisarends/smelt/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/mathisarends/smelt/compare/v0.1.3...v0.1.4
