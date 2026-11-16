# The session record

kern's `session` component hears every event the host hands the core and appends it, one JSON line
each, to a file per session. It is off by default: the `kern` and `se` binaries carry it, and it
runs only where a wiring holds an enabled instance of it. It declares no output, verb or command,
so nothing reads the record over the bus and no tool prints it.

## The switch

One entry in the checkout's ignored overlay, `.se/wiring.toml`, then a restart of the core:

```toml
[instances.session]
component = "session"
# config = { max-bytes = 1048576, keep = 20 }
```

Payloads carry what the host sends, prompts and tool input among them. So the record stays under
the ignored `.se/` folder, no command prints it, and nothing copies it out; switch it on only
where you chose to keep that.

## The line

Each event appends one line to `<folder>/<session>.jsonl`, its fields in this order:

| field | what |
|---|---|
| `time` | when the core heard it, UTC, RFC 3339 with fractional seconds (Go's `time.RFC3339Nano`) |
| `event` | the event's name, as the core hands it to the components |
| `session` | the payload's `session_id` as given, `""` where there is none |
| `payload` | the host's JSON as received, compacted (`json.Compact`); a payload that is not valid JSON is kept as a JSON string |
| `dropped` | in place of `payload`, on a short line: the payload's size in bytes |

```json
{"time":"2026-11-14T09:00:00.123456789Z","event":"Stop","session":"s1","payload":{"session_id":"s1"}}
```

- The file is named by the session id. A missing id, or one that is no safe file name (1 to 128
  characters of `[A-Za-z0-9._-]`, and neither `.` nor `..`), goes to `unknown.jsonl`. A
  sub-agent's events carry its parent's id, so they land in the parent's file.
- The folder is made 0700 on the first write, each file 0600. Lines are only appended, one at a
  time under one lock, so two events never interleave.
- `session.Line` forms the line, a pure function: the event, the payload, the time and whether the
  payload still fits go in; the file name and the line come out.

## The caps

- `max-bytes` (1048576, so 1 MiB per file): a line whose full form would take its file past it is
  written short: `time`, `event`, `session` and `dropped`, no `payload`. So a late event still
  leaves a trace.
- `keep` (20): at start the component keeps the `keep` newest `*.jsonl` files in the folder, by
  modification time, and removes the others. It touches no other file; a missing folder is no
  error.
- A value below 1 for either refuses the start, naming the key.

## The folder

`.se/.runtime/sessions`, relative to the core's working directory: components are handed no root,
and the start runs the core in the checkout's root. A core run by hand with `kern serve` from
another folder writes under that folder. A test passes its own folder and clock through
`session.Options` to `session.New`.

## Failures

A hook fails open. The first failure to write (or to prune at start) is returned to the core once,
which writes it to its log; later failures in the same core return nothing, and the hook's answer
never changes.
