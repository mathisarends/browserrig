# Rule activation and migration

Enable fixed patterns individually in `rules`. Each named setting records a
policy decision:

```yaml
rules:
  layout/definition-order: error
  visibility/internal-public-member: warning
  tests/missing-outcome-check: warning
  tests/unbounded-wait: warning
  tests/missing-await-assertion: warning
```

## Families

Every rule name starts with its family. Enable an individual rule by canonical
name or stable SMT code. The value `on` uses its catalog severity.

Use `smelt check --select typing` or `smelt check --select ALL` to explore the
catalog. In YAML, families and `ALL` can turn rules `off` or cap the
severity of rules already active through an individual entry or applicable
policy. A broad severity with no active matching rule is a configuration error.

```yaml
rules:
  architecture: warning          # Cap rules activated by architecture policy.
  architecture/import-cycle: on  # Enable this named rule at its catalog severity.
```

Precedence within a map is `ALL`, then family, then individual rule.
Style overrides restrict broad settings to source rules. Strict coverage protects
SMT306 from broad settings.

## Layered files

Use `extends: ../smelt.base.yml` for shared, versioned policy. Each file in an
`extends` chain is its own rules layer. A later named setting can replace an
earlier setting. A broad setting can disable or cap matching rules. Use
`smelt config show --sources` for the policy origins and `rule_selectors` matches.

## Information hiding

The visibility reviews cover functions and methods (SMT316), module constants
and type aliases (SMT320), data attributes (SMT335) and APIs whose only observed
consumers are tests (SMT429 and SMT430). Enable the ones your project uses by
individual name. Explore these five together with:

```sh
smelt check --select SMT316,SMT320,SMT335,SMT429,SMT430
```

The static checker cannot prove a rename is safe. Preserve deliberate public
interfaces and review external consumers before editing them.

## Workspace members

In a [uv workspace](configuration.md#uv-workspaces), a member's `smelt.yml` is
one more rules layer. It applies by path to the member's sources and tests:

1. the root rules layers, bases first;
2. the member's `rules`, from the innermost member that contains the file;
3. the closest `style.overrides` entry that sets the rule.

```yaml
# smelt.yml at the workspace root
rules: {complexity/duplicate-function: warning}
```

```yaml
# packages/legacy/smelt.yml
rules:
  complexity: {severity: off, reason: Migrating the legacy service.}
  complexity/duplicate-function: {severity: hint, reason: Review duplication before enforcement.}
```

Here `packages/legacy` reports only `complexity/duplicate-function`, as a hint.
Every other member keeps `complexity/duplicate-function: warning`. Within a member file, the most
specific selector wins, as in any other layer. A rule that only a member enables
stays off in the other members.

A lower member severity needs `{severity: ..., reason: "..."}`, including in
member style overrides. The winning selector supplies the reason. `on` is
compared using the catalog severity. See [reasoned member exceptions](configuration.md#reasoned-member-exceptions).

A member's `architecture` activates the architecture rules the same way the root
architecture does, for example `layers` turns on `architecture/layer-boundary`.
Each local architecture rule uses the architecture of the project that owns its target. See
[member architecture](configuration.md#member-architecture).

## Activation and precedence

The catalog distinguishes three modes, independently of severity:

| Mode | Activation |
| --- | --- |
| `default` | SMT301 and suppression/debt hygiene SMT901–SMT903 |
| `policy` | Explicit architecture/interface policies or real parameters such as import style, mirror layout, mock paths and patch limits |
| `explicit` | Fixed source/test patterns, import cycles and architecture/unclassified-module hints; enable with `rules` or CLI selection |

Declaring layer dependencies activates SMT101; `tests.layout: mirror` activates
SMT401. An empty public list still declares a private API, and a patch limit of
zero still forbids patches. Mere ordering options do not activate SMT313.

A source-convention option enables its rule only where it applies. Set under
`style`, it covers the project. A style override covers the
matching packages, and the rule reports nothing elsewhere. Selecting the same
rule in `rules` or with `--select` enables it everywhere and uses built-in
defaults where no option is set, for example a limit of 5 for SMT345. See
[project-wide options](structure.md#project-wide-options-and-package-overrides)
for the defaults. Use `smelt context MODULE --format json` to inspect the target's
`rule_details`. Entries show the effective severity and whether it came from
`rules`, a policy option or the catalog baseline, along with the source and
reason when available.

```bash
smelt rules --format json
smelt explain visibility/internal-public-member
smelt check --select visibility,tests/unbounded-wait
smelt check --select SMT3
smelt check --select ALL --ignore architecture/import-cycle
```

`--select` replaces normal selection and accepts canonical names, families,
stable code prefixes and `ALL`. `--ignore` accepts the same selectors. A selection enables
fixed patterns without additional policy switches. Architecture/style checks
still require their actual model or parameters where the catalog says so.

Project `rules.<name>: off` disables that rule even under explicit selection.
Package overrides use the same rule names, and the closest package entry wins;
they can disable a global rule, change severity or enable it locally. CLI ignores
apply across the run. Duplicate name/code entries and conflicting settings for
the same concrete package are config errors.

Strict coverage is mandatory: `project.coverage: strict` or `--strict-coverage`
keeps SMT306 enabled outside a select prefix. Lowering its severity, ignoring it
or overriding it inside a package is rejected. Invalid configuration, discovery
and source-analysis errors remain fatal independently of selection.

Debt for inactive rules or disabled packages remains unassessed. Recording and
pruning retain it; disabling checks does not mean violations were fixed. Hint-only
debt is also retained by the debt command. Changed checks compare source under
the current explicit policy on both sides.

Use `smelt init --maintainability` to write a visible selection of source/test
reviews by individual name, with optional hints commented out. Use
`smelt rules --unconfigured` to discover rules to review. Plain `init` infers architecture
and leaves those conventions opt-in;
both commands write an editor schema beside the YAML. The complete small-project
API, package exceptions, editor setup and removed-field/name mapping are in
[configuration and migration](configuration.md). See the
[generated catalog](rules/README.md) for every rule's activation decision.
