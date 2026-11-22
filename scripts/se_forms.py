#!/usr/bin/env python3
"""SE's side of forms: the forms engine (`forms.py`) with the checks SE's filing commands add, as
the command component `forms` that kern's MCP door serves as its tool `forms` (README "Forms"),
and the form gate SE's PreToolUse hook runs on a write through the GitHub tools or `gh`.

The engine stays free of SE's own scripts; this script joins it to them. Its three door commands
only read: nothing is filed, written or sent through them, and none calls GitHub or starts a
model. The fourth, `gate`, is the hook's and not the door's; it writes only its count of refusals
and its log.

- `se_forms.py list [--tree]` prints what `forms.py list` prints: every form of SE's with its
  actions and, for an adapter, its checker.
- `se_forms.py draft <form> [--markdown] [--tree]` prints the JSON `forms.py draft --json` prints:
  `form`, `says`, `fields`, `field_says`, `field_shape` and `schema`; `--markdown` the Markdown
  draft `forms.py draft` prints. An unknown form is answered with the list of forms, exit code 2.
- `se_forms.py check` takes what `forms.py check` takes: a form, or `--action` with `--repo`,
  `--labels` and `--base` to select one as a write would; the text as one of `--body`,
  `--body-file`, `--fields` and `--fields-json`; `--title`; `--render`; `--tree`. Besides,
  `--worktree` names the project whose local list of private terms is read (default: the
  directory it runs in). It checks the text and the title as a filing command would file them
  (`forms.formed` with `[forms] enforce = "refuse"`, a fields object always rendered):
  - the form's own check (`forms.check`, through `work_tickets.form_findings`, or
    `forms.select`'s refused markers with `--action`);
  - the private terms of `forms.private_findings` for the project's root, as
    `work_tickets.form_findings` runs them: a finding names the field and the list, never the term;
  - the name rule, `work_tickets.name_refusal` (what `checked_name` refuses), where the form's
    title field takes `work_tickets:name_refusal` as its shape (`ticket`, `work`) and a title is
    given; it replaces the form's own warning of that shape;
  - for a form of an issue, the SE commands that do not exist, as `work_tickets.refuse_dangling`
    finds them, where the form's own check named none.

**Its answer.** `check` exits 0 whatever it finds, and 2 on a usage error only, as kern's door
answers any other exit code as `command-failed` with a remedy about usage. Its first line is the
verdict, `passes` or `refused: <n> findings` (n the refused ones). A refusal goes on with every
finding as `forms.report` writes it, at most REFUSAL_LINES lines, ending with the line that names
`se_forms.py draft <form>`. A pass goes on with its warnings, one a line, or with `--render` with
the Markdown to file (the warnings then on stderr). Where no form applies to `--action`, it passes
and says `free: no form applies (<action>)` (on stderr with `--render`, the text as given after).

**The gate.** `se_forms.py gate` reads one PreToolUse payload on stdin (Claude Code's, or
Copilot's with `toolName` and `toolArgs`) and answers on stdout one JSON object or nothing; it
exits 0. `scripts/se_hook.sh` runs it only for a guarded call (README "Forms"), with
`--no-python-downloads`, and the hook prints its answer as its whole stdout.

- The tool table (GATE_TOOLS): the tool is the last part of the name, after `__` (Claude Code,
  `mcp__<server>__<tool>`, a plugin's `mcp__plugin_<plugin>_<server>__<tool>`), else after `/`
  (VS Code) or `-` (Copilot CLI); the server part, or the payload's `mcp_server.name` where it
  carries one, holds `github`. Each tool maps to an action and to the arguments that hold its
  body, title, labels and base; `issue_write` is `issue.create` with method `create` and
  `issue.edit` otherwise. A call without a body passes. The repository is `owner`/`repo`.
- The shell reader (SHELL_KEYS to shell_writes): a call of any other tool whose input holds a
  string `command`, `input` or `script` naming `gh` as a word followed by a space (GH_WORD, the
  filter se_hook.sh runs in builtins) is split with shlex at `&&`, `||`, `;`, `|`, `&` and line
  breaks, each part's assignments and prefixes `env`, `command`, `timeout` and `nohup` dropped.
  Each part that is one of these writes is judged as the GitHub tools' call of its action:
  - `gh issue` with `create`, `edit` or `comment` (`--edit-last`: `comment.edit`): `issue.create`,
    `issue.edit`, `comment.create`; `gh pr` with `create`, `edit`, `comment` or `review`:
    `pr.create`, `pr.edit`, `comment.create` (GH_WRITES). Their parts: `--title`/`-t`,
    `--body`/`-b`, `--body-file`/`-F` (`-` reads the part's stdin: a heredoc, a here-string or
    `< <file>`), `--label`/`-l` (repeated or comma-separated), `--base`/`-B`, `-R`/`--repo` or an
    issue's URL; without them the repository is the project's origin, and `gh pr create`'s base
    is the integration branch, as gh takes the default branch.
  - `gh api` on GH_API_PATHS (`repos/<owner>/<repo>/issues`, `.../issues/<n>`,
    `.../issues/<n>/comments`, `.../issues/comments/<id>`, `.../pulls`, `.../pulls/<n>`, `{owner}`
    and `{repo}` as origin's) with POST or PATCH, by `-X`/`--method` or, without one, a field:
    `-f`/`-F`/`--field`/`--raw-field` `title=`, `body=`, `labels[]=`, `base=`, `-F body=@<file>`
    read from the file, `--input <file>` read as JSON. A GET, another endpoint, `gh api graphql`
    and every other command pass.
  - A body it cannot read (UNREAD): from `$(...)`, backticks or a variable, a pipe into
    `--body-file -`, an unquoted heredoc holding `$` or a backtick, a file that does not exist yet,
    or one gh writes itself (GH_OWN_BODY: `--fill`, `--fill-first`, `--fill-verbose`, `--template`,
    `--editor`). It is judged as an empty body: where that selects a form, the write is denied
    (with `warn`, told) naming the remedy, `--body-file <file>` (`-F body=@<file>` for `gh api`);
    where none applies, as for an unmarked comment, it passes and logs one line. The reader
    never runs the command or any part of it.
  - A command it cannot split (an unclosed quote) passes and logs. The first deny among the
    command's writes is the answer.
- Which se.toml decides: the project's (the checkout holding the payload's `cwd`) where its home
  repositories (`forms.home_repositories`) hold the target, else that of the SE this script runs
  from where its home holds it, else the write is free. Its `[forms] gate` (`forms.enforcement`,
  read at `origin/<integration branch>`) is `off` (the default), `warn` or `refuse`;
  `SE_FORMS_GATE=off` in the environment turns it off for the machine whatever se.toml says, and
  `--gate`, for tests only, sets it for the run. The forms are SE's (`forms.load`).
- Selection: `forms.select` for the action, with the call's labels and base. Where the call
  carries no labels or no base, the body's own `<!-- se:form <name> -->` picks among the action's
  forms without that filter; an unmarked body is selected as if the call had no labels. It never
  reads GitHub.
- The check is `check`'s: the same `filed` and `findings`, the private terms read from the
  project's local list.
- The answers: with `refuse` and a refused finding, a `deny` whose reason is `forms.report`'s, its
  tail naming the forms tool (`gate=True`); with `warn` and any finding, `additionalContext` with
  the findings; else nothing. Never an `allow`, which would skip the person's prompt.
- The cap and the hold: each refusal is counted (`forms.count_refusal`) under `forms.target`
  (form, repository, action, the issue's number or the title) in the payload's `session_id`. From
  `[forms] refusals` on, the refusal offers the hold; an issue write labelled `off-form` and not
  `ready` then passes. A private term is never held; comments and pull requests have no hold.
- The failure rule: a payload it cannot read, or any error before it knows that the target is at
  home and a form applies, passes and appends one line, the error and never the body, to
  `<project>/.se/.runtime/forms-gate.log` (GATE_LOG). An error after that denies with
  GATE_FAILED, naming the command to use instead and `SE_FORMS_GATE=off`. A run past
  GATE_SECONDS from the gate's start passes and logs, so a stuck git, uv or disk never holds a
  tool call for the host's own hook timeout.

**Claimed files.** `se_forms.py check-files [PATH ...] [--changed REF] [--root DIR] [--forms DIR]`
checks the files a `file.write` form claims by its `[applies] paths`, each as `forms.py check
--path` checks one. It is neither the door's nor the gate's: `work_tickets.py stop-check`, `push`
and CI's `check` job run it (README "Forms").

- Which files: the PATHs given; or, with `--changed REF`, every file that differs between REF's
  merge base with HEAD and the working tree (committed, staged or not) and every untracked file
  git does not ignore, where a form claims its path. A deleted file is not checked. `--root` is
  the project root the forms' paths are relative to (default: the git checkout holding the
  working directory).
- Which forms: `--forms DIR`'s; else the root's `forms/` (at `origin/<integration branch>` where
  it holds them, `forms.load`); where the root has none, SE's own.
- The switch: with `--changed` it reads se.toml `[forms] files` of the root (`forms.enforcement`,
  at `origin/<integration branch>`, so a branch cannot switch its own check off): `off` (the
  default) checks nothing and says so in one line; `check` checks. Given PATHs are always checked.
- Its answer: per file that breaks its form, one line a refused finding, `<path> (<form>):
  <field>: <fix>`, at most CHECK_FILES_LINES lines in all with a count of the rest, then the line
  that names `forms.py draft --path`; exit code 1. Where nothing is claimed or nothing refuses, one
  line, exit code 0; a usage error, exit code 2. `changed_refusal` gives stop-check and push the
  same lines.

Standard library only; it imports `forms` and `work_tickets` as the scripts beside it."""

from __future__ import annotations

import argparse
import datetime
import importlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: The title shape of the forms whose title is a ticket's name (forms/ticket.toml, forms/work.toml).
NAME_SHAPE = "work_tickets:name_refusal"
NAME_RULE = "name"
DANGLING_RULE = "dangling"
COMMAND = "se_forms.py check"
PASSES = "passes"
#: The gate's bound on its own run, from its start to its answer: past it, the write passes.
GATE_SECONDS = 10.0
#: The gate's log of the writes it let pass without judging, under the project.
GATE_LOG = Path(".se") / ".runtime" / "forms-gate.log"
#: The machine's switch of the gate (README "Machine-local `~/.se/local.toml`").
GATE_SWITCH = "SE_FORMS_GATE"
#: The server part of a guarded tool's name holds this.
GATE_SERVER = "github"
#: The guarded tools: each maps to (action, body, title, labels, base), the arguments that hold
#: them; None where the call has none. `issue_write` is `issue.create` for method `create`.
GATE_TOOLS = {
    "issue_write": ("issue.edit", "body", "title", "labels", None),
    "add_issue_comment": ("comment.create", "body", None, None, None),
    "update_issue_comment": ("comment.edit", "body", None, None, None),
    "create_pull_request": ("pr.create", "body", "title", None, "base"),
    "update_pull_request": ("pr.edit", "body", "title", None, "base"),
    "pull_request_review_write": ("comment.create", "body", None, None, None),
    "add_comment_to_pending_review": ("comment.create", "body", None, None, None),
    "add_reply_to_pull_request_comment": ("comment.create", "body", None, None, None),
}
GATE_FAILED = "SE's form gate failed on this write ({kind}), so it was not sent"
#: The shell reader (the module docstring: The shell reader). The input keys of a shell tool.
SHELL_KEYS = ("command", "input", "script")
#: `gh` as a word followed by a space, as se_hook.sh's filter finds it (`\n` and `\t` as JSON
#: writes a line break or a tab before it).
GH_WORD = re.compile(r"(?:^|[ ;&|(/\n\t])gh ")
#: The prefixes a command may stand behind, and their options that take a value.
SHELL_PREFIXES = {"env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
                  "command": set(), "timeout": {"-s", "--signal", "-k", "--kill-after"},
                  "nohup": set()}
#: The gh writes read: group, then command, to the action, as the GitHub tools' table maps them.
GH_WRITES = {"issue": {"create": "issue.create", "edit": "issue.edit", "comment": "comment.create"},
             "pr": {"create": "pr.create", "edit": "pr.edit", "comment": "comment.create",
                    "review": "comment.create"}}
#: gh's options that take a value, for `gh issue` and `gh pr`, and for `gh api`.
GH_VALUES = {"-t", "--title", "-b", "--body", "-F", "--body-file", "-l", "--label", "-B", "--base",
             "-R", "--repo", "-a", "--assignee", "-m", "--milestone", "-p", "--project", "-H",
             "--head", "-r", "--reviewer", "-T", "--template", "--add-label", "--remove-label",
             "--add-assignee", "--remove-assignee", "--add-project", "--remove-project",
             "--add-reviewer", "--remove-reviewer", "--recover", "--type"}
GH_API_VALUES = {"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header",
                 "--input", "-q", "--jq", "-t", "--template", "--hostname", "--cache", "-p",
                 "--preview"}
#: The options with which gh writes the body itself, so the gate cannot read it.
GH_OWN_BODY = {"--fill", "--fill-first", "--fill-verbose", "--template", "-T", "--editor", "-e"}
#: `gh api`'s endpoints read, each to its action for POST and for PATCH.
GH_API_PATHS = ((re.compile(r"issues"), "issue.create", None),
                (re.compile(r"issues/(\d+)"), None, "issue.edit"),
                (re.compile(r"issues/(\d+)/comments"), "comment.create", None),
                (re.compile(r"issues/comments/\d+"), None, "comment.edit"),
                (re.compile(r"pulls"), "pr.create", None),
                (re.compile(r"pulls/\d+"), None, "pr.edit"))
#: In a prepared command, a value the shell computes ($ or a backtick outside single quotes), and
#: a heredoc by its index.
COMPUTED, HEREDOC = "", ""
HEREDOC_OPEN = re.compile(r"<<(-?)[ \t]*(\\|'|\")?([A-Za-z0-9_.-]+)(?(2)['\"]?)")
UNREAD = ("{said}: SE cannot read this body ({why}), so it cannot check it against the {form} "
          "form. Write the body to a file and pass {remedy}.")
COMPUTED_WHY = "the shell computes it: $(...), backticks or a variable"


class Shell(Exception):
    """A command the reader cannot split: the call passes, and the log says why."""


def prepared(text: str) -> tuple[str, list[tuple[bool, str]]]:
    """The command with COMPUTED for each $ and backtick the shell expands, each heredoc's
    operator replaced by HEREDOC and its index, line breaks as `;`, comments and line
    continuations dropped; and the heredocs, each (quoted, body)."""
    out: list[str] = []
    docs: list[tuple[bool, str]] = []
    pending: list[tuple[str, bool, bool]] = []
    quote = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if quote == "'":
            quote = None if c == "'" else quote
            out.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            following = text[i + 1]
            if following == "\n":
                i += 2
                continue
            out.append(following if quote == '"' and following in "$`" else c + following)
            i += 2
            continue
        if c in "$`":
            out.append(COMPUTED)
            i += 1
            continue
        if quote == '"':
            quote = None if c == '"' else quote
            out.append(c)
            i += 1
            continue
        start = i == 0 or text[i - 1] in " \t\n;&|()"
        if c in "'\"":
            quote = c
        elif c == "#" and start:
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c.isdigit() and start:
            digits = re.match(r"\d+(?=[<>])", text[i:])
            if digits:
                i += digits.end()
                continue
        elif text.startswith("<<", i) and not text.startswith("<<<", i):
            opened = HEREDOC_OPEN.match(text, i)
            if opened:
                out.append(f" {HEREDOC}{len(docs) + len(pending)} ")
                pending.append((opened.group(3), bool(opened.group(2)), opened.group(1) == "-"))
                i = opened.end()
                continue
        elif c == "\n":
            out.append(" ; ")
            i += 1
            for delimiter, quoted, tabs in pending:
                lines = []
                while i < n:
                    end = text.find("\n", i)
                    end = n if end < 0 else end
                    line = text[i:end]
                    i = end + 1
                    if (line.lstrip("\t") if tabs else line) == delimiter:
                        break
                    lines.append(line.lstrip("\t") if tabs else line)
                docs.append((quoted, "".join(line + "\n" for line in lines)))
            pending = []
            continue
        out.append(c)
        i += 1
    if quote is not None:
        raise Shell(f"an unclosed {quote} quote")
    return "".join(out), docs


def shell_parts(text: str) -> list[tuple[list[str], tuple[str, str] | None]]:
    """The command split at `&&`, `||`, `;`, `|` and `&` with shlex: each part's words and its
    stdin, ("text", <text>), ("file", <path>), ("pipe", ""), ("unread", <why>) or None."""
    import shlex
    line, docs = prepared(text)
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split, lexer.commenters = True, ""
    try:
        tokens = list(lexer)
    except ValueError as error:
        raise Shell(str(error)) from error
    parts: list[tuple[list[str], tuple[str, str] | None]] = []
    words: list[str] = []
    stdin: tuple[str, str] | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token.startswith(HEREDOC) and token[1:].isdigit():
            quoted, body = docs[int(token[1:])] if int(token[1:]) < len(docs) else (True, "")
            stdin = ("text", body) if quoted or not re.search(r"[$`]", body) else (
                "unread", "an unquoted heredoc holding $ or a backtick")
            continue
        if not token or any(c not in "();<>|&" for c in token):
            words.append(token)
            continue
        if "<" in token or ">" in token:
            target = tokens[index] if index < len(tokens) else ""
            index += 1
            if token == "<<<":
                stdin = ("unread", COMPUTED_WHY) if COMPUTED in target else ("text", target + "\n")
            elif token.endswith("<"):
                stdin = ("unread", COMPUTED_WHY) if COMPUTED in target else ("file", target)
            continue
        if words:
            parts.append((words, stdin))
        words, stdin = [], ("pipe", "") if token.endswith("|") or token == "|&" else None
    if words:
        parts.append((words, stdin))
    return parts


def unprefixed(words: list[str]) -> list[str]:
    """The words of one part without its assignments and the prefixes SHELL_PREFIXES names."""
    words = list(words)
    while words:
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words.pop(0)
            continue
        prefix = words[0]
        if prefix not in SHELL_PREFIXES:
            break
        words.pop(0)
        while words and words[0].startswith("-") and words[0] != "-":
            option = words.pop(0)
            if option in SHELL_PREFIXES[prefix] and words:
                words.pop(0)
        if prefix == "timeout" and words:
            words.pop(0)
    return words


def options(words: list[str], valued: set[str]) -> tuple[list[tuple[str, str | None]], list[str]]:
    """gh's arguments as (option, value) pairs, a flag's value None, and the positionals."""
    found: list[tuple[str, str | None]] = []
    positional: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        index += 1
        if word == "--":
            positional += words[index:]
            break
        if word.startswith("--") and "=" in word:
            found.append(tuple(word.split("=", 1)))  # type: ignore[arg-type]
        elif word.startswith("-") and len(word) > 1:
            if word in valued:
                found.append((word, words[index] if index < len(words) else ""))
                index += 1
            elif not word.startswith("--") and word[:2] in valued:
                found.append((word[:2], word[2:]))
            else:
                found.append((word, None))
        else:
            positional.append(word)
    return found, positional


def repository_of(value: str) -> str:
    """`-R`'s `[HOST/]OWNER/REPO`, or a URL's `<owner>/<repo>`, as the gate compares them."""
    url = re.match(r"https?://[^/]+/([^/]+/[^/]+)", value)
    return url.group(1) if url else value.strip().strip("/")


def read_file(path: str, cwd: str, stdin: tuple[str, str] | None) -> tuple[str | None, str | None]:
    """The text of a body file (`-` stdin) as (text, None), else (None, why it cannot be read)."""
    if COMPUTED in path:
        return None, "the shell computes its file's path"
    if path == "-":
        kind, value = stdin or ("unread", "--body-file - with no stdin the gate can see")
        if kind == "text":
            return value, None
        if kind == "pipe":
            return None, "a pipe into --body-file -"
        if kind == "unread":
            return None, value
        path = value
    where = Path(path).expanduser()
    if not where.is_absolute():
        where = Path(cwd or ".") / where
    try:
        return where.read_text(encoding="utf-8"), None
    except FileNotFoundError:
        return None, f"{path} does not exist before the command runs"
    except (OSError, UnicodeError) as error:
        return None, f"{path} cannot be read: {type(error).__name__}"


class ShellWrite:
    """One gh write of a shell call, with the fields the gate reads of a Write."""

    def __init__(self, write: "Write", said: str, action: str, repo: str) -> None:
        self.cwd, self.session = write.cwd, write.session
        self.said, self.action, self.repo = said, action, repo
        self.body: str | None = None
        self.title: str | None = None
        self.labels: list[str] | None = None
        self.base: str | None = None
        self.number: int | None = None
        self.unread: str | None = None
        self.remedy = "--body-file <file>"
        self.default_base = False

    def text(self, value: str, what: str) -> str | None:
        """A value as given, None (and `unread` set) where the shell computes it."""
        if COMPUTED in value:
            if what == "body":
                self.unread = COMPUTED_WHY
            return None
        return value


def gh_write(write: "Write", words: list[str], stdin, origin: str) -> ShellWrite | None:
    """The write one part's `gh` command makes, None where it makes none the gate reads."""
    if not words or COMPUTED in words[0] or re.split(r"[/\\]", words[0])[-1] not in ("gh",
                                                                                   "gh.exe"):
        return None
    if words[1:2] == ["api"]:
        return gh_api(write, words[2:], stdin, origin)
    found, positional = options(words[1:], GH_VALUES)
    if positional[:2] == ["pr", "review"]:  # its -a and -r are --approve and --request-changes
        found, positional = options(words[1:], GH_VALUES - {"-a", "-r"})
    action = GH_WRITES.get(positional[0], {}).get(positional[1]) if len(positional) > 1 else None
    if action is None:
        return None
    given = dict(found)
    if action == "comment.create" and "--edit-last" in given:
        action = "comment.edit"
    if "--delete-last" in given:
        return None
    target = positional[2] if len(positional) > 2 else ""
    repo = next((value for name, value in found if name in ("-R", "--repo") and value), None)
    repo = repository_of(repo) if repo else (repository_of(target) if "://" in target else origin)
    call = ShellWrite(write, f"gh {positional[0]} {positional[1]}", action, repo)
    number = re.search(r"(\d+)$", target.rstrip("/"))
    call.number = int(number.group(1)) if number and COMPUTED not in target else None
    for name, value in found:
        value = value or ""
        if name in ("-t", "--title"):
            call.title = call.text(value, "title")
        elif name in ("-l", "--label"):
            call.labels = (call.labels or []) + [label.strip() for label in value.split(",")
                                                 if label.strip()]
        elif name in ("-B", "--base"):
            call.base = call.text(value, "base")
        elif name in ("-b", "--body"):
            call.body = call.text(value, "body")
        elif name in ("-F", "--body-file"):
            call.body, call.unread = read_file(value, write.cwd, stdin)
        elif name in GH_OWN_BODY:
            call.unread = f"gh writes it itself ({name})"
    if call.unread:
        call.body = None
    if action == "pr.create" and call.base is None:
        call.default_base = True
    return call


def gh_api(write: "Write", words: list[str], stdin, origin: str) -> ShellWrite | None:
    """The write `gh api` makes on one of GH_API_PATHS, None for a read or another endpoint."""
    found, positional = options(words, GH_API_VALUES)
    if not positional or COMPUTED in positional[0]:
        return None
    owner_repo = origin.split("/")[-2:] if origin.count("/") >= 1 else ["", ""]
    path = positional[0].replace("{owner}", owner_repo[0]).replace("{repo}", owner_repo[1])
    path = path.split("?", 1)[0].strip("/")
    where = re.fullmatch(r"repos/([^/]+/[^/]+)/(.+)", path)
    if where is None:
        return None
    fields = [(name, value or "") for name, value in found
              if name in ("-f", "--raw-field", "-F", "--field")]
    given = [value for name, value in found if name == "--input"]
    method = next((value for name, value in found if name in ("-X", "--method")), None)
    method = (method or ("POST" if fields or given else "GET")).upper()
    action = None
    for pattern, posted, patched in GH_API_PATHS:
        if pattern.fullmatch(where.group(2)):
            action = {"POST": posted, "PATCH": patched}.get(method)
    if action is None:
        return None
    call = ShellWrite(write, f"gh api {positional[0]}", action, where.group(1))
    call.remedy = "-F body=@<file>"
    number = re.fullmatch(r"issues/(\d+)", where.group(2))
    call.number = int(number.group(1)) if number else None
    for value in given:
        text, call.unread = read_file(value, write.cwd, stdin)
        try:
            data = json.loads(text) if text is not None else {}
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        if isinstance(data.get("body"), str):
            call.body = data["body"]
        if isinstance(data.get("title"), str):
            call.title = data["title"]
        if isinstance(data.get("labels"), list):
            call.labels = [str(item) for item in data["labels"]]
        if isinstance(data.get("base"), str):
            call.base = data["base"]
    for name, field in fields:
        key, _, value = field.partition("=")
        if key == "body" and name in ("-F", "--field") and value.startswith("@"):
            call.body, call.unread = read_file(value[1:], write.cwd, stdin)
        elif key == "body":
            call.body = call.text(value, "body")
        elif key == "title":
            call.title = call.text(value, "title")
        elif key == "labels[]":
            call.labels = (call.labels or []) + [value]
        elif key == "base":
            call.base = call.text(value, "base")
    if call.unread:
        call.body = None
    if action == "pr.create" and call.base is None:
        call.default_base = True
    return call


def shell_writes(write: "Write", project: Path | None) -> list[ShellWrite]:
    """The gh writes of a shell call (the module docstring: The shell reader); [] for any other."""
    command = next((write.input[key] for key in SHELL_KEYS
                    if isinstance(write.input.get(key), str)), None)
    if command is None or not GH_WORD.search(command):
        return []
    origin = (sibling("work_tickets").remote_repo(project) or "") if project is not None else ""
    calls = []
    for words, stdin in shell_parts(command):
        call = gh_write(write, unprefixed(words), stdin, origin)
        if call is not None:
            calls.append(call)
    return calls


CHECK_FILES = "se_forms.py check-files"
#: check-files' refusal: its lines in all, the `draft` line among them.
CHECK_FILES_LINES = 10


def sibling(name: str):
    """The script `<name>.py` beside this one, imported when a command needs it."""
    here = str(HERE)
    if here not in sys.path:
        sys.path.append(here)
    return importlib.import_module(name)


#: se_forms.py's commands as one kern component (README "Commands as components"); each command's
#: usage and help come from make_parser.
COMPONENTS = (sibling("se_components").Group(
    "forms", "Forms",
    "SE's forms: list names them, draft gives a form's fields, their instructions and their shape, "
    "and check finds everything SE's filing commands would refuse in a text, or gives the Markdown "
    "to file.",
    ("list", "draft", "check", "gate", "check-files")),)
#: The commands that go through kern where it runs (se_components.routed): all three only read.
INTERACTIVE_COMMANDS = frozenset({"list", "draft", "check"})
#: The commands that change nothing, each with when an agent uses it: kern's MCP door offers them.
READ_ONLY_COMMANDS = {
    "list": "Lists SE's forms with the actions each shapes. Use it to find the form for a text "
            "before writing it.",
    "draft": "Gives a form's fields, what belongs in each (field_says), their shape and a JSON "
             "Schema of them. Use it before writing an issue, a pull request or a report SE "
             "checks.",
    "check": "Checks a text or a fields object against a form as SE's filing commands would: its "
             "first line is passes or refused, then every finding or, with --render, the Markdown "
             "to file. Use it before filing; it files nothing.",
}


def make_parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="se_forms.py", description=__doc__.splitlines()[0])
    commands = top.add_subparsers(dest="command", required=True)
    tree = {"action": "store_true", "help": "read the working tree's forms/ (default: forms/ at "
                                            "origin/<integration branch> where it holds them)"}
    listing = commands.add_parser("list", help="name every form with its actions")
    listing.add_argument("--tree", **tree)
    drafting = commands.add_parser(
        "draft", help="print a form's fields, their instructions, their shape and its schema",
        description="Print the JSON forms.py draft --json prints; --markdown the empty form.")
    drafting.add_argument("form", help="the form, as list names it")
    drafting.add_argument("--markdown", action="store_true", help="print the Markdown draft")
    drafting.add_argument("--tree", **tree)
    checking = commands.add_parser(
        "check", help="check a text against a form as SE's filing commands would",
        description="Check a body or a fields object as a filing command would file it: the "
                    "form's check, the private terms, the name rule and SE's commands. It exits "
                    "0; its first line is passes or refused: <n> findings.")
    checking.add_argument("form", nargs="?", help="the form; without it, --action selects one")
    given = checking.add_mutually_exclusive_group(required=True)
    given.add_argument("--body-file", type=Path, help="the body as a file")
    given.add_argument("--fields", type=Path, help="the field values as a JSON file")
    given.add_argument("--body", help="the body as text")
    given.add_argument("--fields-json", help="the field values as JSON text, as --fields holds")
    checking.add_argument("--title", help="the title it would be filed with")
    checking.add_argument("--render", action="store_true",
                          help="where it passes, the Markdown to file after the first line")
    checking.add_argument("--action", choices=sibling("forms").ACTIONS, metavar="ACTION",
                          help="select the form as a write of this action would: one of "
                               + ", ".join(sibling("forms").ACTIONS))
    checking.add_argument("--repo", help="with --action: the repository written to")
    checking.add_argument("--labels", help="with --action: the labels, comma-separated")
    checking.add_argument("--base", help="with --action: a pull request's base branch")
    checking.add_argument("--worktree", type=Path, default=Path("."),
                          help="the project whose private terms are checked (default: .)")
    checking.add_argument("--tree", **tree)
    gating = commands.add_parser(
        "gate", help="SE's hook: judge one GitHub write's body against its form",
        description="Read a PreToolUse payload on stdin and answer a deny, the findings, or "
                    "nothing (the module docstring: The gate). It exits 0.")
    gating.add_argument("--gate", choices=sibling("forms").GATE_VALUES,
                        help="for tests only: the switch for this run, whatever se.toml says")
    files = commands.add_parser(
        "check-files", help="check the files a form claims, given or changed since a ref",
        description="Check each claimed file as forms.py check --path does: the PATHs given, or "
                    "with --changed every claimed file changed since REF's merge base, committed "
                    "or not, where se.toml [forms] files is check. It exits 1 where one refuses.")
    files.add_argument("paths", nargs="*", type=Path, metavar="PATH", help="a file to check")
    files.add_argument("--changed", metavar="REF",
                       help="check every claimed file changed since REF's merge base with HEAD, "
                            "untracked ones too, where [forms] files is check")
    files.add_argument("--root", type=Path, help="the project root of the forms' paths (default: "
                                                 "the git checkout holding the working directory)")
    files.add_argument("--forms", type=Path, help="read the forms from this folder instead")
    for command in (listing, drafting, checking, gating, files):
        command.set_defaults(run={"list": run_list, "draft": run_draft, "check": run_check,
                                  "gate": run_gate, "check-files": run_check_files}[
                                      command.prog.split()[-1]])
    return top


class Usage(Exception):
    """A usage error: its message is the answer, exit code 2."""


def loaded(options: argparse.Namespace) -> dict:
    forms = sibling("forms")
    try:
        return forms.load(forms.ROOT, tree=options.tree)
    except forms.FormError as error:
        raise Usage(str(error)) from error


def named(forms_by_name: dict, name: str, command: str):
    """The form `name`, or a Usage error answering with the list of forms."""
    if name not in forms_by_name:
        raise Usage("\n".join([f"{command}: no form {name!r}; the forms are:",
                               *sibling("forms").list_forms(forms_by_name)]))
    return forms_by_name[name]


def run_list(options: argparse.Namespace) -> int:
    print("\n".join(sibling("forms").list_forms(loaded(options))))
    return 0


def run_draft(options: argparse.Namespace) -> int:
    forms = sibling("forms")
    form = named(loaded(options), options.form, "se_forms.py draft")
    if options.markdown:
        print(forms.draft(form), end="")
    else:
        print(json.dumps(forms.draft_fields(form), indent=2))
    return 0


def given_text(options: argparse.Namespace) -> tuple[str | None, dict | None]:
    """The body or the field values `check` was given, by whichever of its four options."""
    forms = sibling("forms")
    try:
        if options.body is not None:
            return options.body, None
        if options.body_file is not None:
            try:
                return options.body_file.read_text(encoding="utf-8"), None
            except OSError as error:
                raise Usage(f"{COMMAND}: cannot read --body-file {options.body_file} "
                            f"({error})") from error
        if options.fields_json is not None:
            return None, forms.fields_data(options.fields_json, "--fields-json", COMMAND)
        return None, forms.fields_file(options.fields, COMMAND)
    except forms.FormError as error:
        raise Usage(str(error)) from error


def filed(form, body: str | None, values: dict | None, title: str | None) -> tuple[str, str | None]:
    """The body and the title as a filing command files them: fields rendered through the form,
    a body parsed and rendered again as with `[forms] enforce = "refuse"`."""
    forms = sibling("forms")
    if values is None:
        return forms.formed(form, body=body, enforce=forms.REFUSE), title
    values = forms.answer(form, values)
    title_field = next((item.name for item in form.fields if item.source == "title"), None)
    if title_field:
        if title is not None:
            values[title_field] = title
        elif isinstance(values.get(title_field), str):
            title = values[title_field]
    return forms.render(form, values), title


def chosen(forms_by_name: dict, options: argparse.Namespace, body: str):
    """The form `check` checks against (None: free) and the refused markers selection met."""
    forms = sibling("forms")
    if options.form is None and options.action is None:
        raise Usage(f"{COMMAND}: name a form, or give --action to select one as a write would")
    if options.form is not None and options.action is not None:
        raise Usage(f"{COMMAND}: give a form or --action, not both")
    if options.action is None and any(value is not None for value in
                                      (options.repo, options.labels, options.base)):
        raise Usage(f"{COMMAND}: --repo, --labels and --base select a form; give them with "
                    "--action")
    if options.form is not None:
        return named(forms_by_name, options.form, COMMAND), ()
    work_tickets = sibling("work_tickets")
    labels = [label.strip() for label in (options.labels or "").split(",") if label.strip()]
    try:
        where: dict[str, object] = {"labels": labels, "base": options.base,
                                    "integration": work_tickets.integration_branch(forms.ROOT)}
        if options.repo is not None:
            where.update(repo=options.repo, home=forms.home_repositories(forms.ROOT))
        selection = forms.select(forms_by_name, options.action, body, options.title, **where)
    except (forms.FormError, work_tickets.QueueError) as error:
        raise Usage(str(error)) from error
    return selection.form, selection.findings


def repository(root: Path, given: str | None) -> str:
    """The repository the text would be filed in: `--repo`, else the project's tracker or origin;
    empty where it has neither, so a bare `scripts/…` path counts as no script of SE's."""
    work_tickets = sibling("work_tickets")
    try:
        return work_tickets.resolve_repo(root, given)
    except work_tickets.QueueError:
        return ""


def findings(form, root: Path, repo: str, title: str | None, body: str) -> list:
    """Every finding a filing command would refuse or warn of for `title` and `body`."""
    forms, work_tickets = sibling("forms"), sibling("work_tickets")
    try:
        _, found = work_tickets.form_findings(root, repo, form, title or "", body)
    except work_tickets.QueueError as error:
        raise Usage(str(error)) from error
    title_field = next((item for item in form.fields if item.source == "title"), None)
    if title is None:  # no title given: the body alone is checked
        found = [item for item in found if title_field is None or item.field != title_field.name]
    elif title_field is not None and title_field.shape == NAME_SHAPE:
        refusal = work_tickets.name_refusal(title)
        if refusal:
            found = [item for item in found if not (item.field == title_field.name
                                                    and item.fix == refusal)]
            found.insert(0, forms.Finding(title_field.name, NAME_RULE, forms.REFUSE, refusal))
    if set(form.actions) & set(forms.ISSUE_ACTIONS) and not any(
            item.rule == DANGLING_RULE for item in found):
        try:
            work_tickets.refuse_dangling(repo, COMMAND, body)
        except work_tickets.QueueError as error:
            found += [forms.Finding("body", DANGLING_RULE, forms.REFUSE,
                                    f"{line.strip()}: correct it, or say in Requirements that "
                                    "this issue adds it")
                      for line in str(error).splitlines()[1:] if line.strip()]
    return sorted(found, key=lambda item: item.severity != forms.REFUSE)


def refusal(form, found: list) -> list[str]:
    """`forms.report`'s refusal, its last line naming this script's draft."""
    forms = sibling("forms")
    if form is None:
        return [f"  {item.field}: {item.fix}" for item in found if item.severity == forms.REFUSE]
    lines = forms.report(COMMAND, form, found, refused=True).splitlines()
    lines[-1] = f"The empty form: uv run python {HERE / 'se_forms.py'} draft {form.name}"
    return lines


def run_check(options: argparse.Namespace) -> int:
    forms = sibling("forms")
    forms_by_name = loaded(options)
    body, values = given_text(options)
    form, met = chosen(forms_by_name, options, body or "")
    found = list(met)
    title = options.title
    if form is None:
        rendered = body if body is not None else json.dumps(values)
    else:
        try:
            rendered, title = filed(form, body, values, title)
        except forms.FormError as error:
            raise Usage(str(error)) from error
        root = options.worktree.resolve()
        found += findings(form, root, repository(root, options.repo), title, rendered)
    refused = sum(item.severity == forms.REFUSE for item in found)
    if refused:
        print("\n".join([f"refused: {refused} findings", *refusal(form, found)]))
        return 0
    warnings = [str(item) for item in found]
    if len(warnings) > forms.REFUSAL_LINES:
        warnings = warnings[:forms.REFUSAL_LINES - 1] + [
            f"... and {len(warnings) - forms.REFUSAL_LINES + 1} more findings"]
    if form is None:
        warnings.insert(0, f"free: no form applies ({options.action})")
    if options.render:
        if warnings:
            print("\n".join(warnings), file=sys.stderr)
        print(PASSES)
        print(rendered, end="")
        return 0
    print("\n".join([PASSES, *warnings]))
    return 0


class Write:
    """One guarded GitHub write as the gate reads it from a payload."""

    def __init__(self, payload: dict) -> None:
        self.cwd = str(payload.get("cwd") or "")
        self.session = str(payload.get("session_id") or payload.get("sessionId") or "")
        name = str(payload.get("tool_name") or payload.get("toolName") or "")
        server = payload.get("mcp_server")
        self.tool, part = tool_parts(name)
        if isinstance(server, dict) and server.get("name"):
            part = str(server["name"])
        self.guarded = self.tool in GATE_TOOLS and GATE_SERVER in part.casefold()
        given = payload.get("tool_input")
        if given is None and "toolArgs" in payload:
            given = payload["toolArgs"]
            given = json.loads(given) if isinstance(given, str) else given
        self.input = given if isinstance(given, dict) else {}
        action, body, title, labels, base = GATE_TOOLS.get(self.tool, ("", None, None, None, None))
        if self.tool == "issue_write" and str(self.input.get("method") or "") == "create":
            action = "issue.create"
        self.action = action
        self.body = self.text(body)
        self.title = self.text(title)
        self.labels = self.listed(labels)
        self.base = self.text(base)
        self.repo = "/".join(str(self.input.get(key) or "").strip() for key in ("owner", "repo"))
        number = self.input.get("issue_number")
        self.number = number if isinstance(number, int) and not isinstance(number, bool) else None

    def text(self, key: str | None) -> str | None:
        value = self.input.get(key) if key else None
        return value if isinstance(value, str) else None

    def listed(self, key: str | None) -> list[str] | None:
        value = self.input.get(key) if key else None
        return [str(item) for item in value] if isinstance(value, list) else None


def tool_parts(name: str) -> tuple[str, str]:
    """A tool's name as (tool, server part): `mcp__<server>__<tool>`, `<server>/<tool>` or
    `<server>-<tool>`; ("", "") for any other name."""
    if name.startswith("mcp__") and "__" in name[5:]:
        server, tool = name[5:].rsplit("__", 1)
        return tool, server
    for separator in ("/", "-"):
        if separator in name:
            server, tool = name.rsplit(separator, 1)
            return tool, server
    return "", ""


def checkout(cwd: str) -> Path | None:
    """The git checkout holding `cwd`, None outside any."""
    if not cwd:
        return None
    here = Path(cwd)
    for folder in (here, *here.parents):
        if (folder / ".git").exists():
            return folder
    return None


class Judged(Exception):
    """An error after the gate knows that the target is at home and a form applies."""

    def __init__(self, error: BaseException, write: Write) -> None:
        super().__init__(str(error))
        self.error = error
        self.write = write


def log_line(where: Path | None, error: BaseException | str) -> None:
    """One line in GATE_LOG of `where` (else of SE's own checkout): the error, never the body."""
    folder = where or HERE.parent
    if isinstance(error, BaseException):
        first = (str(error).splitlines() or [""])[0][:200]
        error = f"{type(error).__name__}: {first}"
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        path = folder / GATE_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(f"{stamp} passed unjudged: {error}\n")
    except OSError:
        pass


def deny(reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                              "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}})


def context(text: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                              "additionalContext": text}})


def deciding(write: Write, project: Path | None) -> Path | None:
    """The checkout whose se.toml decides for `write`: the project's where its home holds the
    target, else SE's own where its home does; None: the write is free."""
    forms = sibling("forms")
    roots = [project] if project is not None and (project / "se.toml").is_file() else []
    for root in (*roots, HERE.parent):
        if forms._at_home(write.repo, forms.home_repositories(root)):
            return root
    return None


def gate_form(catalog: dict, write: Write, root: Path):
    """The form that shapes `write` (None: free), and the refused markers selection met."""
    forms, work_tickets = sibling("forms"), sibling("work_tickets")
    body = write.body or ""
    integration = work_tickets.integration_branch(root)
    if write.labels is None or write.base is None:
        have = {label.casefold() for label in write.labels or ()}
        for name in dict.fromkeys(forms.FORM_MARKER_PATTERN.findall(body)):
            form = catalog.get(name)
            if form is None or write.action not in form.actions:
                continue
            if write.labels is not None and not all(label.casefold() in have
                                                    for label in form.labels):
                continue
            if write.base is not None and form.base and write.base != integration:
                continue
            return form, ()
    selection = forms.select(catalog, write.action, body, write.title, labels=write.labels or (),
                             base=write.base, integration=integration)
    return selection.form, selection.findings


def instead(write: Write) -> str:
    if write.action in sibling("forms").ISSUE_ACTIONS:
        return (f"file it with uv run python {HERE / 'work_tickets.py'} file (backlog file for a "
                "ticket)")
    return "check it with the se server's forms tool (se_forms.py check) and send it again"


def judge(text: str, switch: str | None, seen: dict) -> str:
    """The gate's answer for the payload `text`: a JSON object, or "" (it passes); `seen` gets
    the project, where the log goes. A shell call is judged write by write, its first deny the
    answer."""
    project: Path | None = None
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("the payload is no JSON object")
        write = Write(payload)
        project = seen["project"] = checkout(write.cwd)
        calls = [write] if write.guarded else shell_writes(write, project)
    except Exception as error:  # it cannot judge: the write passes, and the log says why
        log_line(project, error)
        return ""
    answers = [answer for answer in (judge_one(call, project, switch) for call in calls) if answer]
    return next((answer for answer in answers if '"deny"' in answer), answers[0] if answers else "")


def judge_one(write, project: Path | None, switch: str | None) -> str:
    """The answer for one write, a GitHub tool's or one gh command's of a shell call."""
    forms = sibling("forms")
    unread = getattr(write, "unread", None)
    try:
        if (write.body is None and unread is None) or write.repo.startswith("/") \
                or write.repo.endswith("/"):
            return ""
        if switch is None and os.environ.get(GATE_SWITCH, "").strip().casefold() == forms.OFF:
            return ""
        root = deciding(write, project)
        if root is None:
            return ""
        gate = forms.enforcement(root)
        switch = switch or gate.gate
        if switch == forms.OFF:
            return ""
        if getattr(write, "default_base", False):  # gh's default base, taken as the integration
            write.base = sibling("work_tickets").integration_branch(root)
        catalog = forms.load(forms.ROOT)
        form, met = gate_form(catalog, write, root)
        if form is None:
            if unread:
                log_line(project, f"{write.said} in {write.repo}: SE cannot read its body "
                                  f"({unread}), and no form applies to an empty one")
            return ""
    except Exception as error:  # it cannot judge: the write passes, and the log says why
        log_line(project, error)
        return ""
    if unread:
        said = UNREAD.format(said=write.said, why=unread, form=form.name, remedy=write.remedy)
        return context(said) if switch == forms.WARN else deny(said)
    try:
        return judged(write, form, list(met), project or root, gate, switch)
    except Exception as error:
        raise Judged(error, write) from error


def judged(write: Write, form, found: list, root: Path, gate, switch: str) -> str:
    """The answer for `write` once `form` applies: its findings judged by `switch`."""
    forms, work_tickets = sibling("forms"), sibling("work_tickets")
    rendered, title = filed(form, write.body, None, write.title)
    found += findings(form, root, write.repo, title, rendered)
    if not found:
        return ""
    command = f"{write.action} in {write.repo}"
    if switch == forms.WARN:
        return context(forms.report(command, form, found, refused=False, gate=True).replace(
            "([forms] enforce = warn); filed anyway", "([forms] gate = warn); sent anyway"))
    if not any(item.severity == forms.REFUSE for item in found):
        return ""
    private = any(item.rule == forms.PRIVATE_RULE for item in found)
    environ = {"SE_SESSION": write.session} if write.session else None
    key = forms.target(form.name, write.repo, write.action, number=write.number,
                       title=write.title or "")
    issue = write.action in forms.ISSUE_ACTIONS
    labels = {label.casefold() for label in write.labels or ()}
    held = issue and work_tickets.OFF_FORM_LABEL in labels and "ready" not in labels
    if held and not private and forms.refusals(key, environ) >= gate.refusals:
        return ""
    count = forms.count_refusal(key, environ)
    offer = work_tickets.OFF_FORM_LABEL if issue and not private and count >= gate.refusals else ""
    return deny(forms.report(command, form, found, refused=True, hold=offer, gate=True))


def run_gate(options: argparse.Namespace) -> int:
    """The hook's gate (the module docstring: The gate): its answer, or nothing, exit 0."""
    started = time.monotonic()
    answer: list[str] = []
    seen: dict = {"project": None}

    def work() -> None:
        try:
            answer.append(judge(sys.stdin.read(), options.gate, seen))
        except Judged as failed:
            kind = type(failed.error).__name__
            answer.append(deny(f"{GATE_FAILED.format(kind=kind)}: {instead(failed.write)}; or "
                               f"set {GATE_SWITCH}=off to send it ungated on this machine"))
        except BaseException as error:  # never a traceback on the hook's stdout
            answer.append("")
            log_line(seen["project"], error)

    runner = threading.Thread(target=work, daemon=True)
    runner.start()
    runner.join(max(0.0, GATE_SECONDS - (time.monotonic() - started)))
    if runner.is_alive() or not answer:
        log_line(seen["project"], f"slow: no answer within {GATE_SECONDS:g} s")
        return 0
    if answer[0]:
        print(answer[0])
    return 0


def project_root(given: Path | None) -> Path:
    """`--root`, else the git checkout holding the working directory, else that directory."""
    if given is not None:
        return given.resolve()
    here = Path.cwd().resolve()
    return checkout(str(here)) or here


def claim_forms(root: Path, folder: Path | None) -> tuple[dict, Path | None]:
    """The forms check-files checks against and the folder `forms.py draft --forms` reads them
    from (None: SE's own): `folder`'s, else the root's, else SE's where the root has none."""
    forms = sibling("forms")
    if folder is not None:
        return forms.load(root, folder=folder), folder.resolve()
    if root.resolve() == forms.ROOT.resolve():
        return forms.load(forms.ROOT), None
    try:
        catalog = forms.load(root)
    except forms.FormError:
        if (root / forms.FORMS).is_dir():
            raise
        return forms.load(forms.ROOT), None
    own = root / forms.FORMS
    return catalog, own if own.is_dir() else None


def changed_files(root: Path, ref: str) -> list[Path]:
    """Every file under `root` that differs between `ref`'s merge base with HEAD and the working
    tree, and every untracked file git does not ignore; a deleted one is not among them."""
    forms, door = sibling("forms"), sibling("git_door")
    base = door.run("merge-base", ref, "HEAD", root=root)
    if base.returncode != 0 or not base.stdout.strip():
        why = (base.stderr.strip().splitlines() or ["no merge base"])[0]
        raise forms.FormError(f"{CHECK_FILES}: --changed {ref}: no merge base with HEAD in "
                              f"{root} ({why}); fetch {ref}, or name another ref")
    top = door.run("rev-parse", "--show-toplevel", root=root)
    if top.returncode != 0 or not top.stdout.strip():
        raise forms.FormError(f"{CHECK_FILES}: {root} is no git checkout; give --root")
    names: list[str] = []
    committed = door.run("diff", "--name-status", "-z", f"{base.stdout.strip()}..HEAD", root=root)
    status = door.run("status", "--porcelain", "-z", "--untracked-files=all", root=root)
    for done, what in ((committed, "diff"), (status, "status")):
        if done.returncode != 0:
            raise forms.FormError(f"{CHECK_FILES}: git {what} failed in {root}: "
                                  f"{(done.stderr.strip().splitlines() or [''])[0]}")
    tokens = [token for token in committed.stdout.split("\0") if token]
    while tokens:
        kind = tokens.pop(0)
        count = 2 if kind[:1] in ("R", "C") else 1
        names += tokens[:count]
        tokens = tokens[count:]
    tokens = [token for token in status.stdout.split("\0") if token]
    while tokens:
        entry = tokens.pop(0)
        names.append(entry[3:])
        if entry[:1] in ("R", "C") and tokens:
            names.append(tokens.pop(0))  # the origin of a rename, gone where it moved
    folder = Path(top.stdout.strip())
    found: list[Path] = []
    for name in dict.fromkeys(names):
        path = folder / name
        if path.is_file() and path.resolve().is_relative_to(root.resolve()):
            found.append(path)
    return found


def file_lines(catalog: dict, root: Path, paths: list[Path], source: Path | None,
               claimed_only: bool = False) -> tuple[list[str], int]:
    """check-files' lines for `paths` and its exit code: the refused findings and the `draft`
    line (1), or the one line that says what passed (0). `claimed_only` skips, before reading
    them, the files no form claims (--changed)."""
    forms = sibling("forms")
    refusing: list[str] = []
    checked = 0
    for path in paths:
        relative = forms._relative(path, root, CHECK_FILES)
        if claimed_only and not any(form.is_file and form.claims(relative)
                                    for form in catalog.values()):
            continue
        text = forms._file_text(path, CHECK_FILES)
        chosen = forms.select(catalog, forms.FILE_ACTION, text, None, path=relative)
        if chosen.form is None and not chosen.findings:
            continue
        checked += 1
        found = list(chosen.findings)
        if chosen.form is not None:
            found += forms.check(chosen.form, forms.parse(chosen.form, text), root=root)
        for item in found:
            if item.severity != forms.REFUSE:
                continue
            if chosen.form is None:
                refusing.append(f"{relative} (no form): {item.field}: {item.fix}")
            else:
                refusing.append(f"{relative} ({chosen.form.name}): "
                                f"{forms._line(chosen.form, item)}")
    if not refusing:
        if not checked:
            return [f"{CHECK_FILES}: no form claims a file checked"], 0
        return [f"{CHECK_FILES}: {checked} claimed "
                + ("file passes its form" if checked == 1 else "files pass their forms")], 0
    room = CHECK_FILES_LINES - 1
    if len(refusing) > room:
        refusing = refusing[:room - 1] + [f"... and {len(refusing) - room + 1} more findings"]
    draft = f"uv run python {HERE / 'forms.py'} draft --path <file> --root {root}"
    if source is not None:
        draft += f" --forms {source}"
    return [*refusing, f"The empty form of each: {draft}"], 1


def changed_refusal(root: Path, ref: str) -> list[str] | None:
    """check-files --changed `ref` for the checkout `root` as stop-check and push run it: its
    lines where se.toml `[forms] files` is `check` and a changed claimed file breaks its form;
    None where the switch is off or every such file passes. Errors raise."""
    forms = sibling("forms")
    if forms.enforcement(root).files != forms.CHECK:
        return None
    catalog, source = claim_forms(root, None)
    lines, code = file_lines(catalog, root, changed_files(root, ref), source, claimed_only=True)
    return lines if code else None


def run_check_files(options: argparse.Namespace) -> int:
    """check-files (the module docstring: Claimed files)."""
    forms = sibling("forms")
    if bool(options.paths) == bool(options.changed):
        raise Usage(f"{CHECK_FILES}: give the files to check, or --changed REF, not both")
    root = project_root(options.root)
    try:
        if options.changed:
            switch = forms.enforcement(root)
            if switch.files != forms.CHECK:
                print(f"{CHECK_FILES}: [forms] files is {switch.files} in {switch.where}; "
                      "nothing checked")
                return 0
            catalog, source = claim_forms(root, options.forms)
            paths = changed_files(root, options.changed)
        else:
            catalog, source = claim_forms(root, options.forms)
            paths = [path if path.is_absolute() else Path.cwd() / path for path in options.paths]
        lines, code = file_lines(catalog, root, paths, source, claimed_only=bool(options.changed))
    except forms.FormError as error:
        raise Usage(str(error)) from error
    print("\n".join(lines))
    return code


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.command == "gate":
        return args.run(args)
    words = [args.command]
    routed = sibling("se_components").routed(
        Path(__file__), words, list(sys.argv[1 + len(words):] if argv is None else argv[len(words):]),
        args.command in INTERACTIVE_COMMANDS)
    if routed is not None:
        return routed
    try:
        return args.run(args)
    except Usage as error:
        print(error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
