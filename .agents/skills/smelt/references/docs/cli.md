# CLI and reports

See the [changelog](../CHANGELOG.md) for new capabilities, fixes and migration notes
by release, including changes to agent workflows and rule defaults.
For the schema 1 to 2 transition, see the [upgrade checklist and parser example](upgrading.md#json-report-consumers).

Most rules are opt-in. Smelt enables declared architecture/package/test policies
without a second switch; only unknown-layer and suppression/debt diagnostics run
by default. Import cycles and unclassified-module hints require explicit selection.
See [rule activation and migration](rule-selection.md) and the
[full catalog](rules/README.md) for the decisions and precedence rules.

`smelt explain information-hiding` describes the shared visibility policy and
lists its five members. Use `--select information-hiding` or
`--ignore information-hiding` wherever rule selectors are accepted. Rule metadata
in `rules --format json`, `explain` and reports adds a `groups` list; individual
diagnostic codes and report schema version 2 remain unchanged.

```bash
smelt init                           # draft smelt.yml from the code (also uv workspaces)
smelt init --maintainability         # write source/test reviews, including information-hiding
smelt init --config other.yml       # write a config and editor schema in that directory
smelt check                          # whole project
smelt check --changed                # only what the working tree introduced since HEAD
smelt check --staged --fail-on warning  # review the actual commit, including new warnings
smelt check --staged --no-cache       # recompute to verify the cached result
smelt check --changed --base origin/main --format json
smelt check --changed --format concise  # one line per finding with repair advice
smelt check --strict-coverage         # fail on omitted or unclassified production code
smelt check --show-coverage --format json  # include the per-file policy inventory
smelt check --select SMT321 --fix --unsafe-fixes  # use None-only defaults after review
smelt context user                   # what applies to a feature, module or path
smelt explain SMT101                 # rationale, examples and config keys of a rule
smelt rules                          # full catalog with activation and severity
smelt debt                           # record today's violations as known debt
smelt debt --prune                   # drop debt entries that were fixed
smelt debt --show src/app            # inspect stored debt for a file/directory
smelt debt --show --format json      # inspect the grouped version-2 baseline
smelt config show                    # the resolved config
smelt config show --sources --format json  # policy inputs and explicit value origins
smelt config schema                  # the JSON schema of smelt.yml
smelt skill install                  # install the release's official skill in this project
smelt skill install --force          # replace an older installed skill completely
```

Normal checks are read-only. `--fix` applies permitted safe ordering fixes.
Opt-in [SMT321](rules/SMT321.md) reviews `parameter or fallback` for optional
parameters with a `None` default. Its rewrite to an explicit `is not None`
conditional also requires `--unsafe-fixes`: falsy values will be preserved and
custom truthiness will no longer be called. Use this only after reviewing intent.
Fixes respect selection, scope, suppressions and accepted debt, then check again.
JSON reports include `fixes.ordering` and `fixes.none_defaults` with modified
files, counts and skip reasons. `--unsafe-fixes` alone performs no writes;
`--staged` cannot be combined with `--fix`.

Exit codes: `0` clean, `1` violations at or above `--fail-on`, `2` config or usage error.
A config entry that points at nothing (a mistyped package, a missing test root) is a
config error, not a silently disabled rule.
Explicit check paths must exist and contain analyzed source or test files; unknown
`--select`/`--ignore` selectors are usage errors. JSON includes the reporting scope, file
count and active rule codes. `--config PATH` works before or after a subcommand.
A stored JSON report explains itself: `scope.mode` is `full`, `changed` or `staged`, and
`comparison` names the requested `base`, the resolved `merge_base`, the
`compared_revision` and `head`, so `passed` from `--changed` reads as "nothing new since
that commit", not as a clean inventory. JSON check reports use `schema_version: 2`.
By default `coverage` contains only the mode, completeness, counts, policy hash,
architecture presence, discovery errors and omitted workspace members. Use
`--show-coverage` for the full policy and per-file inventory. These details include the source and test roots,
workspace members that are not analyzed, module counts per classification, the
composition-root and wiring exemptions, third-party policies per layer, the import
settings (`type_checking`, `transitive`, `cycles`), cross-feature allowances as fields,
and a `policy_hash` that is equal for reports checked under the same resolved config.
The report's `project` names the config, project root and repository root. JSON
finding paths are project-relative; SARIF and GitHub annotation paths are rebased
to the repository root, including when using a nested `--config`.
`smelt context --format json` carries the same import settings, allowances and hash.
With `--format json`, an exit `2` prints a JSON document as well, so an agent needs no
text parser: `{"schema_version": 2, "status": "error", "error": {...}}` with `kind`
(`usage`, `config` or `analysis`), `message`, the rejected `input` (`option`, `value`)
and, for config errors, the `config` file with each issue's YAML `location`. That covers
argument errors (`--fail-on bogus`, an unknown flag) whenever `--format json` is on the
command line; an invalid `--format` value itself is reported as argparse text.

Schema 2 moves repeated visibility-analysis boundaries from each finding's
`expected.usage_scope` into the report's `usage_scopes` array; findings reference
it with `expected.usage_scope_index`. Finding identities and debt fingerprints are
unchanged by presentation grouping. Text groups related late-import SMT313
findings with their affected lines; JSON retains every finding and adds an
`ordering` group. Text and GitHub output show usage limits once; SARIF retains
them in run properties as `usageScopes`. Text omits empty detail fields.
Text and concise output list a repair repeated verbatim by several findings of
one rule once, below the findings; JSON keeps the hint on every finding.
Projects without architecture configuration have no policy-completeness banner
unless strict coverage is requested. Coverage checks and exit codes still apply.

Shared SMT426 helper findings add `shared_helper` groups with the helper identity,
the exact operation location, one repair and every affected test/call line. Text
and concise output show the repair once. JSON retains the individual findings;
totals, exit behavior, debt identities and suppression scope do not change.
Only visible, compatible findings form a group. Distinct operations in one helper
remain separate, including operations on the same physical line.

SMT424 includes `helper_review` call locations and known inference-limit reasons.
An imported body being unassessed does not mean it lacks assertions. Existing
`tests.assertion_helpers` can express a trusted assertion-helper contract; no
additional helper bodies are inferred. SMT104 includes `graph_kind` and
`witness_edges` with each selected import's phase. These are additive schema-2
fields; existing finding identities and default rule activation are preserved.

Valid configurations can also produce warnings, such as cyclic `may_depend_on`
policies. Reports retain these separately from rule violations in JSON
`configuration_diagnostics` (config path, key, severity and message) and SARIF
`toolConfigurationNotifications`. Text and GitHub output include them too.
They count toward the warning total and cause exit `1` with `--fail-on warning`.
Configuration warnings describe the current policy even in scoped/changed checks;
rule selection, source suppressions and accepted debt do not remove them.

`--changed` checks the base commit (HEAD, or the merge-base with `--base`) with today's
config and reports only violations that are new, wherever they show up. Old violations in
an edited file stay quiet, a new import cycle does not.
Changing an import's comment, formatting or alias does not make its existing boundary
violation new; an additional identical violating import still counts as new.

## Agent skill

Every wheel and source distribution includes the official `smelt` skill, its
offline user guides and complete generated rule reference. No
source checkout or documentation download is needed:

```bash
smelt skill install
smelt skill install --destination .codex/skills/smelt
smelt skill install --force
smelt skill install --destination .codex/skills/smelt --force
```

`--destination` is the exact skill directory, relative to the current directory
or absolute; the default is `.agents/skills/smelt`. Installation does not require
`smelt.yml`. It creates missing parents and writes a `VERSION` file identifying
the installing CLI release. This is a project-local install by default; choose
your agent's user-level skill directory explicitly if you want a global install.

An existing destination is an error unless `--force` is supplied. A forced update
replaces the whole skill, including local edits and obsolete references, without
changing sibling skills. It refuses linked destinations and existing paths that
are not skill directories (a directory containing `SKILL.md`). The new bundle is
copied before replacement, and a failed replacement restores the previous skill.
Keep project-specific additions in the project's own instructions.

After upgrading `smelt-cli`, rerun the installation command with `--force` and the
same destination. Package upgrades do not silently rewrite installed skills.
Successful installation exits `0`; destination and filesystem errors exit `2`.
Use `smelt config schema` to print the complete editor schema from the installed
release, or `smelt init` to write it alongside a new policy.
