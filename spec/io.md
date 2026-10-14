# I/O modules: the shape every one follows

Reader: an agent writing, moving or testing an I/O module, or code that needs one.

Processes, the disk, the clock, the network and GitHub are each reached
through exactly one I/O module ([principles 6 to 8](principles.md)). The
clock, `src/internal/io/clock`, is the first and the model for the rest.

## The layout

Each I/O module is one package, `src/internal/io/<name>`, holding four parts:

| part | what it is |
|---|---|
| the interface | what SE asks of the outside thing, and nothing more. The clock's is `Clock`: `Now`, `Sleep`, `After` |
| the real implementation | the one place SE reaches that thing. The clock's is `clock.Real()` |
| the fake | an implementation that behaves, in the same package. The clock's is `clock.NewFake(at)` |
| the contract suite | one function in a `_test.go` file, called by both the fake's test and the real one's |

Code takes the module as an argument: a struct field or a parameter, set
once where the program starts (`cmd/se` hands every command `clock.Real()`).
Nothing reaches for the real thing itself, so a test hands in the fake and a
case replays.

## Fakes behave

A fake keeps its own state and answers from it as the real thing would. It
never scripts answers: a test does not tell it what the next call returns. The
fake clock stands still until it is told to move: `Advance` moves it and fires
every `After` whose time has come, and `Sleep` passes its time at once.

## One contract suite per fake

The contract suite is what the module promises, written once. It takes a way
to make a fresh instance and runs every case against it; the fake's test and
the real one's test each call it. A fake that passes the suite stands in for
the real thing; a fake without one drifts. The clock's suite is `contract` in
`src/internal/io/clock/contract_test.go`.

## Test on fakes, real only in contract tests

Every other test runs on fakes: no wall clock, no sleeping, no network. The
real implementation runs in its contract test alone, kept short.

## The rule

The `io-module` rule (`src/internal/rules/iomodule.go`) holds the line: outside
`src/internal/io/`, no Go file imports `os/exec` or `net/http`, calls the
clock through `time` (`Now`, `Sleep`, `After` and their kin), or opens, reads
or writes files through `os`. Test files are left to principle 8.

What still breaks it today is named in one allowlist,
`src/internal/io/allowlist.txt`, one file and what it reaches per line. It
only shrinks: each I/O module removes its own entries as it lands, the last
empties it, and the rule refuses an entry that matches nothing.
