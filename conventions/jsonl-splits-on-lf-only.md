# JSONL splits on `\n` only — never Node `readline` (hard rule)

Any JS/TS code that reads a JSONL stream or file — a transcript, a session log,
an agent's RPC channel, an eval result set — must frame records on `\n` and
nothing else. **Node's `readline` is not a JSONL reader**, and reaching for it is
the default mistake, because it is the obvious tool and it works on every input
anyone tests with.

This is a claude-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

## The mechanism

`readline` splits on additional Unicode line separators, including **U+2028**
(line separator) and **U+2029** (paragraph separator). Those characters are
*legal, unescaped, inside a JSON string* — `JSON.stringify` does not escape
them, so any record containing prose that passed through a word processor, a
PDF extraction, a CMS, or a model that emitted one will carry them verbatim.

`readline` then cuts the record in half, mid-string. The two halves are not
valid JSON, so the failure is usually a parse error rather than silent
corruption — but it is a parse error on data that is *fine*, appearing only for
certain content, on records nobody can reproduce on request. It reads as
"corrupt log", and the log is not corrupt.

The correct reader is a dozen lines, and
[pi](https://github.com/earendil-works/pi) (MIT) hand-rolls exactly that in
`packages/coding-agent/src/modes/rpc/jsonl.ts` for this reason, saying so in the
docstring: readline "splits on additional Unicode separators that are valid
inside JSON strings and therefore does not implement strict JSONL framing." The
shape:

- A `StringDecoder` on the raw stream, so a multi-byte UTF-8 character split
  across two chunk boundaries is buffered rather than mangled.
- `buffer.indexOf("\n")` in a loop; slice, emit, advance.
- Strip one trailing `\r` per line, for CRLF-written files.
- On `end`, flush `decoder.end()` and emit a final partial line if the file did
  not end with a newline.

The writer side carries the matching commitment — `JSON.stringify(value) + "\n"`
— and the header comment states the contract for consumers outright: framing is
LF-only, payload strings may contain other Unicode separators, split on `\n`
only.

Two things generalize past this one API:

- **A framing bug that only fires on rare characters is a latent bug, not a
  rare one.** Its probability tracks your input's provenance, not your code, so
  it lands the day someone pastes real-world prose in — which is the day the
  data matters.
- **Decoding and framing are separate concerns and must not be delegated to one
  convenience API.** `readline` bundles them and picks the wrong framing;
  `StringDecoder` does only the decoding, which is the part actually worth
  importing.

## The check

Grep any JS/TS log or transcript parser for `readline`, `createInterface`, and
`split(/\r?\n/)` on decoded text, and confirm the framing is LF-only. Python is
not exempt by default either: `str.splitlines()` splits on U+2028/U+2029 (and
more) for the same reason. Use `split("\n")`, or iterate the file object, which
does not.

Filed alongside [`truncated-producers-taint.md`](truncated-producers-taint.md)
from the same read of pi: that convention is about a record that is complete-
looking but short, this one is about a record that is complete and gets cut by
the reader. Both end as a parse-level surprise in a consumer that did nothing
wrong.
