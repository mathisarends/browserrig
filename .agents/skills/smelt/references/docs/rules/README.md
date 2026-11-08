# Rules

| Code | Name | Category | Activation | Severity |
| --- | --- | --- | --- | --- |
| [SMT101](SMT101.md) | layer-boundary | dependencies | policy | error |
| [SMT102](SMT102.md) | cross-feature-import | dependencies | policy | error |
| [SMT103](SMT103.md) | third-party-denied | dependencies | policy | error |
| [SMT104](SMT104.md) | import-cycle | dependencies | explicit | error |
| [SMT105](SMT105.md) | shared-imports-feature | dependencies | policy | error |
| [SMT106](SMT106.md) | composition-root-leak | dependencies | policy | error |
| [SMT107](SMT107.md) | private-module-import | dependencies | policy | error |
| [SMT108](SMT108.md) | package-import-fanout | dependencies | policy | hint |
| [SMT109](SMT109.md) | facade-export-gap | dependencies | policy | hint |
| [SMT301](SMT301.md) | unknown-layer | structure | default | error |
| [SMT302](SMT302.md) | forbidden-package-name | structure | policy | error |
| [SMT305](SMT305.md) | unclassified-module | structure | explicit | warning |
| [SMT306](SMT306.md) | incomplete-coverage | structure | policy | error |
| [SMT307](SMT307.md) | missing-required-module | structure | policy | error |
| [SMT308](SMT308.md) | import-style | structure | policy | error |
| [SMT309](SMT309.md) | forbidden-module-docstring | structure | policy | error |
| [SMT310](SMT310.md) | forbidden-future-annotations | structure | policy | error |
| [SMT311](SMT311.md) | unnecessary-future-annotations | structure | policy | hint |
| [SMT312](SMT312.md) | no-private-modules | structure | policy | error |
| [SMT313](SMT313.md) | public-definitions-first | structure | explicit | error |
| [SMT314](SMT314.md) | bundled-instance-assignment | structure | explicit | error |
| [SMT315](SMT315.md) | prefer-match-type-dispatch | structure | policy | hint |
| [SMT316](SMT316.md) | internal-public-member | structure | explicit | warning |
| [SMT317](SMT317.md) | internal-static-helper | structure | explicit | hint |
| [SMT318](SMT318.md) | redundant-str-enum-value | structure | explicit | hint |
| [SMT319](SMT319.md) | prefer-package-import | structure | explicit | hint |
| [SMT320](SMT320.md) | internal-public-module-symbol | structure | explicit | warning |
| [SMT321](SMT321.md) | implicit-optional-default | structure | explicit | warning |
| [SMT322](SMT322.md) | deep-object-navigation | structure | explicit | hint |
| [SMT323](SMT323.md) | no-base-class-prefix | structure | explicit | error |
| [SMT324](SMT324.md) | prefer-str-enum-discriminator | structure | explicit | hint |
| [SMT325](SMT325.md) | missing-module-docstring | structure | policy | error |
| [SMT326](SMT326.md) | no-base-class-suffix | structure | explicit | error |
| [SMT327](SMT327.md) | secret-settings-field | structure | explicit | warning |
| [SMT328](SMT328.md) | redundant-dishka-provider | structure | explicit | hint |
| [SMT329](SMT329.md) | caller-before-callee | structure | explicit | hint |
| [SMT330](SMT330.md) | package-only-dunder-all | structure | explicit | error |
| [SMT331](SMT331.md) | yaml-file-extension | structure | policy | error |
| [SMT332](SMT332.md) | compose-file-name | structure | policy | error |
| [SMT333](SMT333.md) | prefer-callable-instance | structure | explicit | hint |
| [SMT334](SMT334.md) | private-class-constant | structure | explicit | warning |
| [SMT335](SMT335.md) | internal-public-attribute | structure | explicit | warning |
| [SMT336](SMT336.md) | redundant-module-name | structure | explicit | hint |
| [SMT401](SMT401.md) | test-location | tests | policy | error |
| [SMT420](SMT420.md) | private-test-access | tests | explicit | error |
| [SMT421](SMT421.md) | forbidden-test-mock | tests | policy | error |
| [SMT422](SMT422.md) | string-patch-target | tests | explicit | error |
| [SMT423](SMT423.md) | excessive-test-patches | tests | policy | error |
| [SMT424](SMT424.md) | test-without-outcome-check | tests | explicit | warning |
| [SMT425](SMT425.md) | test-only-checks-possibly-empty-data | tests | explicit | warning |
| [SMT426](SMT426.md) | unbounded-test-wait | tests | explicit | warning |
| [SMT427](SMT427.md) | independent-test-case-loop | tests | explicit | hint |
| [SMT428](SMT428.md) | async-mock-without-await-check | tests | explicit | warning |
| [SMT429](SMT429.md) | test-only-public-function | tests | explicit | warning |
| [SMT430](SMT430.md) | test-only-public-attribute | tests | explicit | warning |
| [SMT431](SMT431.md) | nondeterministic-test-data | tests | explicit | warning |
| [SMT901](SMT901.md) | unused-suppression | meta | default | warning |
| [SMT902](SMT902.md) | suppression-without-reason | meta | default | error |
| [SMT903](SMT903.md) | resolved-debt | meta | default | warning |

## Rule groups

Enable a coherent policy with one `rules` entry. Individual settings override the group within the same map; closest-package settings still win.

- `information-hiding`: Keep implementation details private, including APIs exposed only for tests. Includes SMT316, SMT320, SMT335, SMT429, SMT430. Use `smelt explain information-hiding` for the scope and limits.

`smelt rules` prints the same catalog in the terminal.
