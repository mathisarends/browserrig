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
- `stability`: one MutationObserver per document and its last mutation time.
  Its guard prevents duplicate observers. Document/context destruction disposes
  of the world and observer together.

Scripts throw only the fixed codes in `ScriptError`. Unexpected exception text
is never returned to the model. ESLint and Prettier cover main files and helpers;
Python contract tests guard script names, inline JavaScript and error codes.
