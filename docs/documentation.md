# Building the documentation

## Documentation

se's documentation is one HTML file, published at the GitHub Pages site of SE's home,
`https://<owner>.github.io/<repository>/`, which `scripts/se_home.py` derives from the checkout's
origin; a project that publishes elsewhere sets `docs_url` in `se.toml` `[project]`.

`docs.md` is its manifest: it lists se's notes as chapters and restates none of them. The obs
component (`[components.obs]` in `se.toml`, found beside SE's repository) builds it:

```sh
uv run python scripts/build_docs.py --destination <file outside the repository>.html
```

obs builds it, every decision deck and the Timeline with the adapter component `obs-html`, which
it finds among the machine's installed components only. Each build installs it where it is missing
(`obs-components install obs-html`) and fails, naming that command, where none can be installed.

`build_docs.py --install-html` does only that; the setup scripts in se's checkout, the `check` job
and the docs workflow run it before they build. A build fails on every warning obs prints, except
obs-html's that it cannot name its own commit (`build_docs.py` `KNOWN_WARNINGS`).

The build reads a copy of the repository in which no note asks for a verdict, so the worked
decision note shows as a page to read, with no Send; the note itself still asks, for the decks
built from it.

In the same copy the rule book shows as one table of its rules, grouped by section, each row
opening to its rule; `scripts/rule_book.py` makes the table and a note per rule from `rules.md`.
`--document <file>` also writes the obs Document the page was built from.

The README is the first chapter and the command line the second: `docs/command-line.md` holds one
`cmd` fence, `sh RUNME.sh --help`, so the chapter is SE's help as each build prints it. The build
passes obs `--execute-commands`, which lets obs run every `cmd` fence of the chapters and every
`cmd silent` fence of any Markdown file in the copy it reads; a failing one fails the build.

The build first runs RUNME once in that copy, so what RUNME installs lands in the home and in the
copy, never in the checkout. RUNME there takes the pinned `se` from `~/.se/bin`, as the copy holds
no `.git` to fetch it by and no modules to build it from: on a machine that lacks it,
`bash scripts/bootstrap.sh --binary` in the checkout places it first, as the docs workflow does.

Any obs warning fails the build, so a broken link, a missing note or a paragraph longer than obs's
default limit fails it. The suite runs the build (`tests/test_docs.py`),
and the workflow `.github/workflows/docs.yml` builds and publishes it to GitHub Pages on each push
to `main`; a failed build publishes nothing, so the previous artifact stays.

The Timeline, `timeline.html` beside the documentation, builds itself from the issues and
releases of the repositories in `se.toml` `[timeline]`: SE, obs and kern (a bare name lies beside
SE's home). The same workflow rebuilds it hourly and on each issue event.

It is one obs table, a row per issue or release: its repository, place, date, number, title and
status. It groups the rows by place (Today, Needs you, Next, Backlog, Done), puts the newest first
in each, and pages them; a backlog idea shows as waiting for your input. When the page opens, it
asks GitHub for what changed since the hourly snapshot and shows that where GitHub answers.

[scripts/timeline.py](../scripts/timeline.py) owns what shows where, the live read, and how a
repository the workflow's token cannot read shows as a named gap instead of failing the build.
