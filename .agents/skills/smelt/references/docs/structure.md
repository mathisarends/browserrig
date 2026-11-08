# Package contracts and source conventions

Choose canonical configuration filenames once per project:

```yaml
structure:
  file_naming:
    yaml_extension: yaml        # yaml or yml, without a dot
    compose_basename: compose   # compose or docker-compose
```

[SMT331](rules/SMT331.md) reports other YAML extensions;
[SMT332](rules/SMT332.md) reports other Compose basenames. The two policies are
independent: omitting either allows both spellings for that part of the name.
No separate `rules` entry is needed; use one to adjust severity or disable a check.

Checks cover lowercase `.yaml` and `.yml` files below the directory containing
the Smelt configuration, including that configuration, `.github/workflows` and
deployment directories outside Python source roots. Tool/cache directories and
`project.exclude` paths are skipped. Dotted Compose variants such as
`docker-compose.override.yml` retain their variant; custom names such as
`stack.yaml` are not classified as Compose files. File contents are not parsed.

Findings give the expected path. Rename deliberately, resolve existing target
files and update references in CI, scripts, `extends` and `docker compose -f`
arguments. Smelt does not rename files or update references automatically.
Use reasoned `ignore.paths` entries for required external filenames.
`smelt context` includes the declared filename policy; path-scoped, changed and
staged checks apply to these files too.

The [pre-commit benchmark](https://github.com/mathisarends/smelt/blob/main/docs/agent-workflow.md#canonical-configuration-filenames)
records the additional cost with 1,000 YAML files, including complete hook timings.

Prefer private module functions for class-internal static helpers by enabling:

```yaml
rules:
  internal-static-helper: warning
```

`smelt check --select SMT317` reviews helpers such as `_build_match_clause` and
`_created_at_sort` when they need no instance or class state. Findings include a
collision-free `suggested_name`, the destination module, observed internal
references and `automatic_extraction: false`. Move the helper deliberately and
update its class-qualified callers. Decorated, inherited or subclassed classes
and external static APIs are conservatively retained. A missing finding in those
cases does not mean the rule is inactive; inspect its documented scope with
`smelt explain SMT317`.

To bundle a facade import with its implementation imports, set a package API
threshold explicitly:

```yaml
structure:
  contracts:
    application-api:
      match: backend.features.*.application
      bundle_imports_at: 2
```

SMT108 reviews `from ...application import PasswordHasher` alongside
`from ...application.errors import AccountAlreadyExistsError`. Its JSON finding
includes `proposed_exports` for missing static re-exports, or `blocked_exports`
and a `cycle` witness when the proposed facade edges close a known runtime cycle.
After reviewing the exports, callers can import both names from `application`.
Other APIs such as `auth.domain.validation` do not contribute to this threshold.
No source is rewritten. `no-cycle-found` describes the explicit runtime import
graph and does not prove package initialization or dynamic imports safe.

Declare a repeated structure or public interface explicitly. Contracts apply to
Python packages matched by a dotted pattern, independently of feature or layer
names. A whole-segment `*` in `match` selects one package segment.

```yaml
structure:
  contracts:
    feature-shape:
      match: app.features.*
      required: [application.api, domain]
      public: [application.api]
    library-api:
      match: toolkit
      required: [models]
      public: ['.']
```

This requires every matching feature to contain an `application.api` module or
package and a `domain` module or package. Callers outside that feature may import
only `application.api`. Internal code may use its own implementation modules.
`toolkit` exposes its package facade; `toolkit.models` remains private to outside
callers, while the facade can deliberately re-export symbols from it.

- `required` contains exact relative dotted module names. Namespace packages and
  split source roots work too. Excluded files do not fulfill a contract.
- `public` entries are relative module patterns. `'.'` means the matching package
  itself; `api` exposes exactly that module/package, and `api.**` deliberately
  exposes that subtree. Each pattern must match analyzed code. Omit `public` to
  check structure only; `public: []` closes the package to outside imports.
- Structure and interface contracts are additive: an import must satisfy every applicable contract.
  Wiring and composition roots follow the same interface rules. Existing layer
  and feature restrictions still apply, and public entries do not classify code
  into architecture roles or grant cross-feature access.
- SMT307 reports missing required modules or public entry points. A `match`
  pattern selecting no analyzed package is a configuration error. SMT107 reports
  private imports, including explicit module-valued aliases through facades;
  intentional symbol re-exports through a public entry point are permitted.
- These are static module contracts. They do not check `__all__`, arbitrary
  attribute access, dynamic loading, symbol-level visibility, or behavior. Module
  presence alone does not establish a useful implementation; choose contracts
  that reflect an intentional design, rather than creating empty template files.

`smelt context` includes applicable contracts, required/public modules, missing
entries and the visibility of an existing or planned module. Check JSON includes
resolved contracts under `coverage.contracts`. `smelt explain SMT107` and
`smelt explain SMT307` describe the rules. No contract is inferred automatically
or enabled by default for consumer projects.

## Module names without private prefixes

Require descriptive module/package names while keeping private helpers inside
them:

```yaml
structure:
  contracts:
    module-names:
      match: app
      private_modules: forbid
```

SMT312 (`no-private-modules`) rejects `_service.py`, `_internal/` and other
underscore-prefixed module/package names, including double-underscore names.
Python's special `__init__.py` and `__main__.py` files are allowed; arbitrary names
such as `__service__.py` are still checked. This exception applies to files, not
dunder-named package directories.

Use `service.py` with public entry functions and `_helper` functions instead.
The rule checks names independently of exports: a private-prefixed module is
still a finding when it declares `__all__` or its symbols are re-exported. Function,
method, class and attribute names are unaffected. This naming convention does
not change the public entry points declared by architecture API contracts.

Omitting `private_modules` adds no naming policy. A more specific package can set
`private_modules: allow`; contradictory policies on the same concrete package
are config errors. Existing reasoned `ignore` entries can cover individual legacy
modules. Excluded source and test directories follow the normal analysis scope.
Namespace packages and split import roots are supported, with one finding per
offending logical package rather than duplicate findings for its portions.

`context` exposes the effective convention as `naming_policy`, including planned
files. Check JSON includes it in `coverage.contracts`. Rename deliberately and
update imports and facade exports; Smelt never renames files or symbols itself.

## Separate instance attribute assignments

To keep field initialization readable, opt into `SMT314`:

```yaml
structure:
  contracts:
    instance-fields:
      match: app
      rules:
        bundled-instance-assignment: error
```

This reports `self.log, self.control = log, control` and chained assignments such
as `self.log = self.control = value`. Prefer:

```python
self.log = log
self.control = control
```

The rule checks assignments writing multiple direct attributes of an instance
method's first positional parameter, including differently named receivers and
async methods. Local unpacking stays valid. Mixed unpacking with only one direct
instance target is allowed; nested object attributes and assignments in nested
helper bodies are outside the check. Nested classes use their own receiver.
Recognized static/class methods are excluded; arbitrary decorator and assignment
aliases are not inferred. Only analyzed production modules are covered.

The closest package rule wins; `rules: {bundled-instance-assignment: off}` exempts
a package. Effective rule severities appear in `context`, including planned modules.
This is an optional readability convention. There is no autofix: parallel
assignment, properties, swaps and unpacking failures can change behavior when
split. When unpacking a computed pair, consider unpacking into locals first and
then assigning each field while preserving evaluation timing.

## Type dispatch with match/case

`SMT315 prefer-match-type-dispatch` suggests reviewing longer positive
`isinstance`/`elif` chains over the same simple name:

```yaml
structure:
  contracts:
    event-dispatch:
      match: app
      type_dispatch:
        style: match
        min_branches: 3
```

The default threshold is three type-tested branches; it counts branches rather
than members of a type tuple/union. The closest policy wins. Use `style: allow`
for an exception and `rules: {SMT315: error}` if this convention must fail CI.
The default severity is a hint, since class-pattern equivalence needs review.

```python
match event:
    case OutputValidated() | OutputValidationFailed():
        if event.call_id is not None:
            control_calls.add(event.call_id)
    case ToolCalled() if event.call.id not in control_calls:
        calls[event.call.id] = event.call
        yield ToolStarted(event.call)
```

An independent preceding `if isinstance(event, SessionEvent): events.append(event)`
must stay independent: an event may need both observation and dispatch. An inner
body condition must not become a case guard without checking fallthrough: when
an OutputValidated event has no call ID, its original branch still consumes it.
Existing and-guards are recorded separately from body conditions.

Supported heads use the builtin isinstance or an unambiguous top-level builtins
import alias, a simple subject name and type names/dotted names/tuples/unions.
Additional and-guards are allowed. Independent if statements, mixed subjects,
negative/or tests, type factories, parameterized types, computed subjects and
unsupported branches are not combined. One hint describes the whole supported
chain; elif suffixes are not reported independently.

Checker names bound anywhere in a file are conservatively excluded unless they
are a single recognized top-level builtin import. A parameter in another function
can therefore suppress the same checker spelling for the file. Star imports and
recognized builtin-module mutations also disable detection. Assignment aliases,
dynamic namespace changes and runtime type identities are not inferred; a type
name may refer to something unsuitable for a class pattern.

There is no autofix. Match evaluates its subject once, and subclasses, custom
instance checks, guard effects and runtime type values need manual review. Declared
Python minima before 3.10 are excluded; unknown minima retain an explicit version
review requirement. JSON exposes the subject, branch types, guards and Python
target; context exposes the policy for existing and planned modules. Only analyzed
production sources are covered. Changed/debt comparisons track branch identities
and multiplicity, so an additional branch cannot hide behind an accepted chain.
See the Python reference for
[match semantics](https://docs.python.org/3/reference/compound_stmts.html#the-match-statement).

## Relative and absolute imports

Declare the style explicitly, globally for a root package or for selected
packages. This example uses absolute imports by default and relative imports
within infrastructure packages where at most one leading dot is needed:

```yaml
structure:
  contracts:
    default-style:
      match: app
      imports: {style: absolute}
    adapter-style:
      match: app.features.*.infrastructure
      imports: {style: relative, max_relative_level: 1}
```

In the relative scope, `from .models import Record` is preferred over
`from app.features.users.infrastructure.models import Record`. An import requiring
`from ..domain import User` instead uses the absolute path. The limit counts
leading dots; set `max_relative_level: 2` to permit and prefer parent imports up
to two dots. Imports between different root packages and third-party/standard
library imports stay absolute. `style: absolute` requires absolute imports even
for siblings. Omitting `imports` preserves either form.

The most specific enclosing package with an `imports` policy wins. Conflicting
styles for the same concrete package are config errors. Initializers and namespace
packages use their logical package, independently of filesystem source roots.
SMT308 reports the expected form without rewriting bindings or aliases. As with
other import rules, `architecture.imports.type_checking` controls guarded imports.
Ruff's [TID252](https://docs.astral.sh/ruff/rules/relative-imports/) already covers
forbidding parent-relative imports; Smelt additionally checks the preferred form
under these package contracts.

## Suggestions to bundle implementation imports

Several imports from the same package can suggest a missing public facade:

```python
from app.features.users.application.get_user import GetUser
from app.features.users.application.update_user import UpdateUser
from app.features.users.application.delete_user import DeleteUser
```

Enable an advisory threshold on the package that would own the common API:

```yaml
structure:
  contracts:
    application-api:
      match: app.features.*.application
      bundle_imports_at: 3
```

SMT108 suggests the matching `application` package facade once one outside file
imports at least three distinct implementation modules there. Repeated imports,
multiple symbols from one module, and imports in separate callers do not inflate
the count. Imports from inside the package and symbols already exported by its
facade do not count. The threshold is configurable and disabled when omitted.

For overlapping `bundle_imports_at` and `export_at` contracts matching the same
concrete package, the pattern with more literal segments wins. An exact package
match overrides a wildcard. Identical equally specific settings produce one
decision; conflicting equally specific settings are configuration errors.
These thresholds do not inherit into unmatched child packages.

After deliberately defining the exports, the caller can use a combined import
such as `from app.features.users.application import DeleteUser, GetUser, UpdateUser`.
Review dependency direction and cycles before adding exports. This is a `hint`
by default; it does not fail the usual error gate. Choose `public: ['.']` instead
to require facade-only imports regardless of their count. No facade or import is
rewritten automatically.

When the exports already exist, enable `rules: {prefer-package-import: hint}`
or `--select SMT319`. For example, if `app.observation.__init__` directly exports
`Observe` and `Snapshot`, it suggests replacing
`from app.observation.models import Snapshot` with a package import that can join
`from app.observation import Observe, Snapshot`. Every imported name must have a
direct, unconditional public re-export; aliases and relative imports are preserved
in suggestions. Internal imports, package initializers, uncertain exports and
unscanned third-party packages are excluded. See [SMT319](rules/SMT319.md).

To find names that are widely imported but missing from a facade, configure
[SMT109 `facade-export-gap`](rules/SMT109.md):

```yaml
structure:
  contracts:
    browser-api:
      match: app.browser
      export_at: 3
      count_tests: false  # default; true also counts discovered test files
```

SMT109 counts distinct outside modules importing each public implementation name,
including mixed import statements that SMT319 cannot shorten yet. It reports one
hint per name and package, anchored at the definition, with source/test importer
lists, existing re-exports elsewhere and a concrete import suggestion. Repeated
imports and aliases in one caller count once. Static re-export chains are resolved
to the defining module. Imports already using a package facade do not count as
deep coupling. Only selected source and discovered tests are visible; excluded,
unselected and external consumers are not assessed.
Other package exports and explicit `__all__` re-exports in regular modules are
listed as context, without selecting a canonical import path.

Private names and `TYPE_CHECKING`-only imports never count, even when the global
import policy includes type-checking edges. Namespace packages without an analyzed
initializer, conflicting or uncertain bindings, star exports and dynamic facade
exports recognized through `__getattr__`, dynamic `__all__`, `exec` or namespace
inspection calls are skipped. Arbitrary runtime mutation is not inferred.
Static `__all__` is respected; an existing binding excluded
from it needs only an `__all__` change. A contract that forbids access to its own
facade does not receive export suggestions. `count_tests: true` requires
`export_at`, whose minimum is two importers.

The cycle check tests the proposed facade-to-definition dependency against the
analyzed explicit runtime import graph and reports a deterministic return path.
`no-cycle-found` does **not** establish safe initialization: dynamic imports,
implicit initializer execution and import order are outside this check. Existing
cycles can also appear in the witness. Treat the result as a design review;
frequency alone does not establish API ownership. No source or configuration is
changed, and there is no automatic facade rewrite. Once exports are
deliberately added, SMT319 can suggest the corresponding caller imports, and
`public: ['.']` can enforce a chosen facade boundary through SMT107.

## Module headers and Python-version-aware annotations

Module docstrings and future imports can be governed independently:

```yaml
# Optional override of the minimum supported version, when metadata is absent:
project:
  python_version: "3.14"

structure:
  contracts:
    source-conventions:
      match: app
      module_docstrings: forbid
      future_annotations: when-needed
```

Choose one canonical `module_docstrings` convention for a package:

- `require` enables SMT325: every analyzed production module needs a non-empty
  initial docstring, including empty files, `__init__.py` and `__main__.py`.
  Empty/whitespace-only strings, comments, later strings and class/function
  documentation do not satisfy the requirement.
- `forbid` enables SMT309: no initial module docstring, even an empty one.
  Class/function documentation and ordinary string values are unaffected.
- `allow` explicitly permits either style in a more specific package. Omitting
  the field inherits the closest explicit package policy, or adds no policy
  when none exists. Only analyzed source files are checked; separately discovered
  tests and excluded files are unaffected.

The single policy field keeps `require` and `forbid` mutually exclusive for each
module; a more specific package can deliberately choose the opposite convention.
For an individual file exception, mark the file with a reason:

```python
# smelt: ignore-file[SMT325] -- Empty compatibility facade; documented in the public API.
```

Use `SMT309` instead when retaining a docstring under `forbid`. Normal suppression
checks require reasons and flag unused exceptions. Smelt never adds or removes
documentation automatically.

`future_annotations` supports three modes:

- `allow`: preserve the import, including a deliberate runtime compatibility use.
- `forbid`: SMT310 rejects `from __future__ import annotations` at any version.
- `when-needed`: SMT310 rejects it for a declared minimum of Python 3.14 or newer.
  With an earlier or unknown minimum, SMT311 gives a conservative review hint for
  modules with no detected postponement need. It retains imports for unresolved
  or quoted forward references, `TYPE_CHECKING`, runtime annotation inspection,
  decorators, inherited models and unknown annotation expressions. Builtin
  generics and unions are considered with their supported Python version.

Version detection uses the nearest project's `requires-python` in
`pyproject.toml`, with an explicit `project.python_version` taking precedence.
The configured version means the **minimum supported version**. The interpreter
running Smelt and `.python-version` are not evidence that older Python releases
are unsupported. Monorepo members keep their own declared requirements; an
independent member with missing/invalid metadata stays unknown. Lower bounds are
validated with Python packaging specifiers; exclusions alone never raise the
inferred minimum. For external source roots, discovery also checks their import
root's parent; declare an override when the project boundary is otherwise unknown.

The report exposes versions, metadata provenance and uncertainty under
`coverage.python_targets`; context JSON includes `python_target` and the effective
`header_policy`, and findings explain which version was used.

Python 3.14 [defers annotations by default](https://docs.python.org/3.14/whatsnew/3.14.html#deferred-evaluation-of-annotations),
but the future import still changes their runtime representation. These are
source conventions and advisory evidence, not proof of equivalent runtime
behavior. Smelt never removes imports or documentation automatically. Verify
annotation consumers and tests before removing an import, and use an explicit
package exception where its string-based behavior is intentional.

## Definition order with execution dependencies

Enable `SMT313 public-definitions-first` to put the public interface first while keeping
prerequisites, binding versions and runtime boundaries intact:

```yaml
structure:
  contracts:
    definition-order:
      match: app
      ordering:
        module:
        - docstring
        - future-imports
        - imports
        - dunder-assignments
        - type-vars
        - public
        - private
        - main-guard
        class:
        - class-attributes
        - init
        - dunders
        - public
        - private
        constants_exempt: false
        fix: safe-only
      rules:
        public-definitions-first: error
```

The defaults are shown above. Each list must contain its categories exactly once;
module docstrings, future imports and imports form the fixed prefix, and the
main guard belongs last. Use package `rules: {public-definitions-first: off}` to exempt a package.
The closest explicit rule setting wins; ordering options alone do not activate the check. This extends `smelt.yml` package contracts rather than adding
a second `[tool.smelt.ordering]` configuration source.

The analyzer partitions module and directly nested class bodies into sections.
Within each section it computes a stable topological order: configured priority,
with prerequisites inheriting the priority of their dependents. Relative order
inside a category stays unchanged. Functions may refer to helpers in their bodies
before those helpers are defined. Decorators, defaults, class creation,
assignments and eagerly evaluated annotations have different timing; existing
reads and later rebindings are preserved. Unknown Python minima are treated
conservatively as eager; the future import or a declared Python 3.14+ minimum
defers annotations, while defaults remain eager.

For a declared Python 3.10+ minimum, unions of recognized, unshadowed builtin
types and `None` in function annotations are modeled without an execution barrier.
For example, `str | bytes` does not pin an otherwise movable helper on Python
3.12/3.13. Imports from `builtins`, including aliases, are recognized; other
imported or user-defined types, subscriptions and unions in defaults remain
conservative execution boundaries. Shadowing and later rebindings still preserve
definition-time reads. Modules with explicit global/nonlocal mutation declarations
or detected writes to the `builtins` module retain conservative union barriers.

On Python 3.12/3.13, keep `from __future__ import annotations` when the chosen
public-first order uses forward references. SMT311's `when-needed` policy retains
the import in that case. Without it, eager annotation dependencies take priority
over public-first order; Smelt does not require inserting a future import just
to reorder definitions. `Self` is an alternative only when a method's return
contract follows the receiver's subclass, such as returning `self` or constructing
`cls`. A method that always constructs the named base class cannot promise `Self`.

Calls, unknown decorators, imports, control flow, `TYPE_CHECKING`, mutations,
operator/protocol evaluation and unsupported generic constructs are execution
barriers. Smelt keeps them in place. Literal construction through recognized
typing TypeVar/ParamSpec/TypeVarTuple factories has a dedicated category.
Consecutive overload/implementation and property getter/setter/deleter families
remain atomic. Noncontiguous property families are pinned. Function bodies,
including classes defined inside them, are outside this ordering analysis.

`constants_exempt: true` treats private uppercase module constants like public
definitions, allowing them to remain above the interface. Class attributes have
their own category. `__init__`, `__new__` and `__post_init__` share the initializer
category; other dunders precede ordinary public/private methods by default.
Names use the underscore convention; ordering does not infer semantic visibility
or rename symbols. If another tool changes visibility, run it before ordering.

Plain `smelt check` is always read-only. Request fixes explicitly:

```bash
smelt check --select SMT313 --format json
smelt check --select SMT313 --fix --format json
```

The fixer applies only visible, non-suppressed, non-debt sections within the
requested scope, then checks again. `fix: off` disables writes for a package.
Changed checks operate on affected reported sections, including any existing
ordering debt in a section that also contains a new inversion. Debt pruning and
changed comparisons track inversion identities, so adding a new inversion cannot
hide behind an existing aggregate finding.

Bounded fixes move source blocks, comments and their leading whitespace together;
they preserve UTF-8/BOM, newline convention and file permissions. Nested edits
are rendered together and the resulting AST must equal the approved permutations.
Use the project's formatter afterwards to normalize spacing. Symlinks, external
source roots, concurrent edits, formatter/suppression regions, tab indentation,
runtime introspection and uncertain class/decorator behavior require manual
review. A misplaced main guard or import is diagnosed but never moved across an
execution barrier automatically. These bounds do not prove arbitrary Python
reflection or hidden runtime effects equivalent; verify types and behavior.

JSON includes expected/original order, semantic inversions, fixability and reasons.
`coverage.ordering` identifies the analyzed files and barriers; `context` exposes
the effective `ordering_policy`, including planned placement. With `--fix`, JSON
also includes `fixes.ordering` with modified files, section counts and skipped
reasons. Every other rule keeps its existing behavior; no visibility or module
rename fixer is implied by this option.

## Internal public functions, methods and static helpers

Adopt visibility and helper-placement conventions per package:

```yaml
structure:
  contracts:
    internal-helpers:
      match: app
      rules:
        internal-public-member: warning
        internal-static-helper: hint
    deliberate-api:
      match: app.integrations
      rules:
        internal-public-member: 'off'
        internal-static-helper: 'off'
```

[SMT316](rules/SMT316.md) reviews public module functions and ordinary instance
methods with no observed use outside their defining module or class, including
unused definitions. For example, `emit` called or passed as `self.emit` only
inside `Browser` gets a private-name suggestion such as `_emit`. The JSON lists
internal reference lines and distinguishes unused members from internal helpers.
Existing private-name collisions get a distinct suggested name. Explicit module
exports, decorated members and inherited/subclassed classes are preserved.
Discovered test accesses count as external uses; SMT429 separately reviews
test-only public module functions when that named rule is enabled.

[SMT317](rules/SMT317.md) suggests moving an internal `@staticmethod` helper
to a private module function, such as `Browser._normalize(value)` becoming
`_normalize(value)`. It supports sync/async helpers and builtin decorator aliases;
class-namespace dependencies, inheritance, extra decorators and possible external
method accesses are excluded. Neither rule performs automatic changes.

Both named rules use the closest explicit package rule setting. They are advisory:
unknown same-named attribute access outside a class conservatively preserves its
methods, and external users or dynamic reflection cannot be ruled out. Review
the intended API before renaming or extracting a helper. `smelt context` includes
the effective policies even for planned files.

## Internal public module constants and type aliases

Enable [SMT320](rules/SMT320.md) separately to review module data:

```yaml
rules:
  internal-public-module-symbol: warning
```

The rule covers single, unconditional uppercase assignments and PEP 695
`type Alias = ...` declarations in implementation modules. It suggests reviewing
private names for data used only internally, including definitions with no observed
uses. Package initializers, static exports, imports and analyzed re-exports, test
accesses and escaped module values preserve visibility. Public signatures and
fields also preserve annotation dependencies, including quoted and transitive
type aliases: `Secret.value: SecretValue` is evidence for keeping `SecretValue`
public, not a reason to rename it automatically or require a facade export.

Rebound or shadowed names, star imports, dynamic export declarations and detected
namespace reflection are excluded. Ordinary assignment-style aliases and classes
are outside this check. Findings expose the selected roots, exclusions and
unassessed consumers through `usage_scope`; absence of observed use does not prove
an external API is unused. The closest package rule override applies. Review the
API before renaming; there is no automatic rewrite.
