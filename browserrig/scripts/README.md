Each main `.js` file defines one `browserrig<Name>` function and receives one
options object. `Script.load` loads packaged resources once and composes the
declared `lib/` helpers into a local wrapper. Python argument models serialize
aliases to JavaScript; result adapters validate returned data.

`Frame.run` and `run_on_owner` share dispatch and error translation. Only owner
scripts receive the embedding iframe element as `this`. Seed additionally
receives resolved DOM objects through CDP object arguments. Object handles stay
within their session and are released by their owner. User gestures are explicit
and reserved for element operations.

The isolated world's `globalThis.__browserrig` namespace holds:

- `dom`: supplementary closed shadow roots and native click-listener metadata;
  reset and reseeded for each extraction.
- `elements`: snapshot token and DOM node references; overwritten by the next
  snapshot. Content extraction does not replace these references.
- `stability`: persistent mutation observers and scroll listeners for the document,
  accessible frame documents and shadow roots, plus the last activity time. Each
  probe discovers newly attached roots and checks finite animations and visible
  busy content. Detached roots are disconnected; document/context destruction
  disposes of the remaining observers. Cross-origin frames are probed through CDP.
- `findIndex`: the page text of the last find, with its session and the
  `stability` time it was read at; typing reuses it while the document is
  unchanged. Closing the find bar clears it.
- `secretFields`: fields that received a secret; their text is masked with
  `-webkit-text-security`.
- `secretTarget`: the field focused when secret typing started; typing aborts
  as soon as focus leaves it.

Scripts throw only the fixed codes in `ScriptError`. Unexpected exception text
is never returned to the model. ESLint and Prettier cover main files and helpers;
Python contract tests guard script names, inline JavaScript and error codes.

Shared helpers own composed ancestry, shadow/slot traversal, visibility, geometry,
hit testing and element resolution. Snapshot style lookups are cached for one run;
elements store no closures. Visibility follows `checkVisibility` plus inert
ancestors, allowing descendants to override inherited `visibility:hidden`.
Content traversal preserves such descendants and balances truncated code fences.
