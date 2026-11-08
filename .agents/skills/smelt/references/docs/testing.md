# Test policies

## Optional test quality policies

Test mirroring and test quality are independent.
When `project.test_roots` overlap, the most specific declared root owns each test,
independent of list order. Mirror paths are relative to that root.

Enable the policies that match your unit-test conventions in the existing YAML
configuration:

```yaml
tests:
  layout: mirror
  forbid_mocks_in:
  - '**/tests/**/domain/**'
  max_patches_per_test: 2
  assertion_helpers:
  - tests.assertions.assert_user
  timeout_helpers:
  - tests.timing.deadline
  quality_exclude: []
rules:
  private-test-access: error
  string-patch-target: error
  test-without-outcome-check: warning
  test-only-checks-possibly-empty-data: warning
  unbounded-test-wait: warning
  independent-test-case-loop: hint
  async-mock-without-await-check: warning
  test-only-public-function: warning
```

| Code | Checks |
| --- | --- |
| SMT420 | Private production imports, module access and direct known/typed instance reads |
| SMT421 | Recognized mocking operations in the configured test paths, including conftest fixtures |
| SMT422 | Literal string targets of patch, patch.dict, patch.multiple and MonkeyPatch setattr/delattr |
| SMT423 | Recognized patch calls exceeding the per-test limit, including decorators, patch.object and MonkeyPatch attribute replacement |
| SMT424 | No recognized explicit outcome assertion (warning by default) |
| SMT425 | Every recognized outcome can disappear or pass trivially on empty input (warning) |
| SMT426 | Known waits without local deadlines or replacement of the asyncio scheduler clock (warning) |
| SMT427 | Small literal loops containing candidate independent cases (hint) |
| SMT428 | Call-only assertions on known async mocks without corresponding await evidence (warning) |
| SMT429 | Public module functions accessed from tests but not from other analyzed production modules (warning) |
| SMT430 | Public instance/class data attributes read from tests but not accessed by production code outside their class (warning) |

Every policy is opt-in; `0` is a valid patch limit. Globs are relative to the
configuration root, not each test root. `quality_exclude` does not disable mirror
checks or exclude production code. Rule selection, severity overrides, inline
suppressions and debt work normally. Plain checks remain read-only.

The shared analysis recognizes unittest.mock import aliases and the standard
pytest-mock fixtures (`mocker`, `class_mocker`, `module_mocker`, `package_mocker`,
`session_mocker`) on test/fixture functions. Explicit MockerFixture annotations
are also recognized. MonkeyPatch receivers include the standard `monkeypatch`
fixture, explicit annotations, constructors, aliases and `.context()` scopes.
Only its `setattr`/`delattr` attribute replacements count as patches; environment,
mapping and directory setup remain separate. Local shadowing and common
control-flow bindings are respected. Locally declared fixture overrides take
precedence over standard fixture names; external plugin overrides remain unknown.

SMT424 accepts assert other than literal `assert True`, recognized pytest
exception/warning checks, unittest.TestCase assertions, known mock interaction
assertions and imported qualified assertion helpers. A mere unused
`pytest.raises(...)` context object supplies no check. Known Mock/AsyncMock
constructors, simple aliases, default patch context results and explicitly typed
fixtures establish mock receivers; arbitrary methods named `assert_*` do not.
An awaited `asyncio.wait_for(known_event.wait(), timeout=...)` or an equivalent
Event wait inside a timeout context that raises on expiry also supplies
observable lifecycle evidence. `move_on_after` and configured timeout helpers
alone do not. A frozen scheduler clock can still defeat that
deadline. One direct call to an unambiguous, undecorated, non-generator helper in
the same file also supplies evidence, including nested functions and async helpers
executed with `await` or `asyncio.run`. Assertions whose failure could be swallowed
by a try/context scope do not supply helper evidence; known raising timeout
contexts retain it. Uncalled definitions, unexecuted coroutines, imported helper
bodies, fixture execution, callbacks and further helper calls remain unknown.
Positive validation/smoke tests can justify an exception. `assert result`
still counts: this rule detects missing explicit checks, not assertion quality,
reachability or correct behavior. Neither a literal threshold nor syntax proves
that a test protects a requirement.

SMT425 complements outcome recognition: if every recognized check is inside a
possibly empty result loop, or is a positive `assert all(...)` over possibly empty
input, it asks for review. Nonempty literal collections, immutable tuple/string
aliases and literal builtin `range` calls are recognized. Mutable collection
aliases remain unknown because other calls can empty them. An additional independent outcome,
explicit empty-result comparison, or alternative empty case is retained. Prefer
complete generated/expected mappings over loops that check only returned files.
This check does not prove collection cardinality or assertion reachability.
Possibly empty iteration inside a directly executed helper or around its call
retains the same review. An assertion on an unfiltered collection does not prove
that a filtered subset contains any items; prefer expected artifacts or an
explicit check of the collection actually iterated.

SMT426 checks known subprocess calls for their own timeout, and known asyncio
Event/Task/Future and subprocess Process waits for local guards such as `wait_for`, `asyncio.timeout`,
AnyIO/Trio timeout contexts or configured qualified `timeout_helpers`. Async
cancellation cannot bound a blocking synchronous subprocess. A known loop's
`time` replacement is reported separately because its deadlines may freeze too.
Async processes are recognized from awaited `asyncio.create_subprocess_exec` /
`create_subprocess_shell` and explicit `asyncio.subprocess.Process` annotations.
Each awaited `wait()` or `communicate()` needs its own guard: a preceding bounded
read or `kill()` does not bound the later exit wait.
The same direct helper calls are reviewed for known waits. Findings point at the
operation inside the helper and include its name and call line in JSON. An async
deadline around the caller guards async waits, while synchronous subprocesses
still need their own timeout. Arguments, arbitrary callbacks and transitive
helper execution are not inferred.
External runner deadlines and general task/fixture flow are not resolved.
Bounded real-boundary polling and `asyncio.sleep(0)` are valid; positive sleeps
are not prohibited. SMT427 only suggests parametrization for narrow literal-loop
candidates and avoids common stateful replay, handoff and transaction lifecycles.
Review both heuristics in context before treating their findings as defects.

SMT428 reviews known async interactions checked only through call assertions or
asserted call history. `assert_called_once_with` can pass even when an async
operation was never awaited; use `assert_awaited_once_with` when execution matters.
Direct AsyncMock callables and explicitly async methods on known class specs are
supported, including aliases and consistent local/conftest fixture returns.
Synchronous methods, unknown specs and arbitrary children of an unspecced mock
are not assumed async. An explicit await-history check on the same mock, negative
call checks or `assert_not_awaited` for intentional scheduling preserve that intent.
Simple single-assignment locals can carry history into assertions; inherited or
arbitrarily decorated methods, transitive helpers and general data flow remain
outside scope. A finding concerns an individual test, not the suite's ability to
catch the regression. There is no automatic assertion rewrite.

SMT429 reviews functions such as `drag_gesture` that are used inside their own
module but exposed publicly only to tests. Its finding points at the definition,
suggests `_drag_gesture` and lists the test locations in JSON. Review the rename
and update internal references; prefer testing the public `drag` operation that
calls the helper. Deliberate direct helper tests can retain a reasoned exception
to SMT420 when that policy is also enabled. Functions in `__all__`, production
re-exports, decorated functions and methods are excluded. Aliased and relative
imports count as production consumers; star imports and escaped module values
conservatively preserve public visibility. External users, packaging entry points
and arbitrary dynamic access remain review limits. Checks do not rename code.

Enable SMT430 with `rules: {test-only-public-attribute: warning}` or
`--select SMT430`. It reviews public attributes such as `worker.pending` when only
tests read them outside the owning class. It shares the member-use analysis with
SMT316, SMT317 and SMT429 and suggests an available private name. Known
constructors, annotations, fixtures and class re-exports establish test receivers.
Possible production accesses preserve visibility, including unresolved same-named
receivers. Decorated/inherited classes, properties, descriptors, slots and custom
attribute hooks are excluded. Prefer observing public behavior; keep deliberate
public state with a reasoned suppression. See [the rule](rules/SMT430.md) for
scope and limits.

The scope is the discovered `test_*.py`, `*_test.py` and conftest files. Test
functions use the usual test_ prefix; methods in Test-prefixed classes and direct
unittest.TestCase/IsolatedAsyncioTestCase subclasses are supported. Custom pytest
collection settings and inherited tests are not resolved. Helper modules outside
this inventory and transitive fixture/helper effects are not traversed. A fixture
in a permitted shared conftest can therefore introduce mocking into a domain test
without this path policy detecting that dependency. Direct production constructors,
explicit instance annotations and annotated local/conftest fixture returns support
SMT420. Consistent known constructor/alias fixture returns and yields are also
recognized, including fixed tuple components when unpacked. Inferred fixture
types carry separate provenance; fixture bodies are never executed. Class fixture
types stay in their own class. Private instance writes are excluded for
immutability probes. Unknown factories, conflicting fixture outputs, arbitrary
attribute types and reflection are not inferred. String target variables and f-strings are outside SMT422's
literal check. A passing static report is not evidence that tests ran or protect
their intended behavior.

Patch-count comparisons track individual syntactic calls, including multiplicity,
so accepted debt cannot hide an added or replaced patch. JSON includes policy,
operation locations and a test-quality coverage summary; `smelt context` exposes
the test policy before files are written. No automatic patch or test rewrites occur.

## Evaluate a test-quality change

Use a fixed project snapshot and compare the old/new analyzer on the same policy.
Then execute the chosen pytest boundary and, when justified, introduce a specific
plausible regression in that disposable snapshot. Confirm that the test fails for
the intended reason and still passes with the real implementation. Promote the
small failing example and an intentional valid neighbor into Smelt regressions.
Review false positives and missed cases; a lower finding count alone is no goal.

The optional maintainer runner records this comparison without installing either
version or changing policy. Replace the example paths with your snapshot, baseline
import root and selected test scope:

```bash
uv run python scripts/evaluate.py --config ../application/smelt.yml \
  --baseline ../smelt-0.1.4 --reports ../smelt-evaluation \
  --pytest-target tests/unit
```

Both import roots must contain `smelt/__init__.py`; checkouts and extracted wheels
are supported. Use `--candidate`, `--python`, `--test-python`, `--pythonpath` and
repeatable `--pytest-arg` options when the project uses a separate test environment.
`--select` defaults to SMT42; use `--select ''` for the adopted policy. Enable new
candidate-only policies in a separate review run; old versions reject unknown
configuration fields. Keep reports outside inspected source roots.

`evaluation.json` contains the configuration SHA256, optional `--source-revision`,
commands, return codes, deadlines, raw logs and added/removed/updated findings,
including multiplicity. Analysis exit 1 means findings and permits comparison.
Runner exit 0 / `complete` means the requested stages completed; without explicit
pytest targets, `pytest.executed` is false. Test failures return 1 / `tests-failed`.
Invalid analysis, malformed output, timeouts or incomplete pytest collection return
2 / `error`; invalid analysis never starts pytest. Neither status proves test
effectiveness, and this runner performs no automatic mutation or source fixes.

For complementary checks use Ruff's annotation and pytest-style rules: ANN201/
ANN202 for return annotations, ANN001 for parameters, N801 for class naming, and
PT011 for selected exception assertions missing a meaningful match/check. The
last rule can be configured for exception names that need these constraints.
Smelt does not enforce class grouping, one assertion/action, a universal ban on
control flow, assertion strength, fixture placement, duplicate test bodies,
network isolation or frozen clocks in this release. Those require separate policy
and evidence; multiple checks can legitimately describe one scenario.

## Mirrored source paths

With `tests.layout: mirror` the path of a test decides: `tests/billing/test_invoice.py`
needs `app/billing/invoice.py`, and a package test `tests/billing/test_billing.py` needs
`app/billing/`. Not every module needs a test, but a test whose source is missing or
elsewhere is an error. The message names the fix where it can: the right directory, the
right file name (`test_session_infrastructure_repository.py` should be named
`test_repository.py`), a neighbouring module with a similar name, or a missing `{root}` in
the pattern.
Imports through package facades count as imports of the module that defines the
name, so `from app.channels.application import ChannelCommands` points at
`application/commands/`. A move needs that evidence (or a test named exactly after its
subject, marked `"evidence": "name"`); a similar file name alone suggests nothing.
Otherwise the JSON lists `expected.candidates`: the imported modules, nearest first, with
the names imported from them, the facade they came through and their mirrored test path.
A test importing two modules of its name (`application/bootstrap.py` and
`infrastructure/bootstrap.py`) gets both as candidates and no move.

`tests.mirror` sets the convention relative to the test root: the default
`{path}/test_{module}.py` drops the root package, `{root}/{path}/test_{module}.py` keeps it,
and `unit/{path}/{module}_test.py` puts tests under `tests/unit/` with a suffix. In a uv
workspace each test root mirrors the package of its own member. Deliberately unmirrored
tests go in `tests.unmirrored` (e.g. `["tests/e2e/**"]`); `tests.mirror_suffixes: true`
also allows `test_invoice_<topic>.py`.

Mirroring repeats file names: `auth/presentation/test_router.py` and
`user/presentation/test_router.py`. pytest's default import mode only tells them apart
inside packages, so without `__init__.py` in the test directories it stops with "import
file mismatch". Prefixing the names (`test_auth_presentation_router.py`) works around that
but breaks the mirror; set the import mode instead, which `smelt init` points out:

```toml
[tool.pytest.ini_options]
addopts = ["--import-mode=importlib"]
```
