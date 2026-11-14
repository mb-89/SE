#!/usr/bin/env python3
"""SE's script commands as kern components (README "Commands as components").

A script's command group is one component, `components/<name>/`: its `component.toml`, which
`work_tickets.py docs` writes from the script's argparse parser, and an `__init__.py` that calls
`attach`, so the component answers each declared command with the script's own code. The command
line does not change: `<script>.py <command>` runs as before, and an interactive command goes
through kern where kern serves this checkout (`routed`), else directly; any copy of the script
routes there, the plugin's as much as the checkout's own (`serves`).

- **Declared:** a script that runs components names them in its `COMPONENTS` (each a `Group`) and
  its read-only commands in `INTERACTIVE_COMMANDS`, and builds its parser with `make_parser`; it
  names those that change nothing, each with its MCP description (when an agent uses it), in
  `READ_ONLY_COMMANDS`, which kern's MCP door offers;
  `SCRIPTS` lists those scripts. `declared` reads each group's commands, their usage and help from
  that argparse parser (a parser without subcommands is one command, the script itself, `""` in its
  group); `components` merges a group two scripts name into one component (render: timeline.py and
  deck.py), and `declaration` writes one group's `component.toml` text; `reference`
  renders the README's command reference from the declarations as kern's own reader
  (`kern.declaration`) reads them, so the README shows the catalog kern checks at its start.
- **Attached:** `attach` answers each command by running the main of the script its first word
  names, one of the component's scripts, with the command's words and arguments in this process. A call's first argument may be `--se-cwd=<dir>`, the
  directory the command runs in; without it, kern's root. What it answers:
  - exit code 0: the text is what it wrote to stdout, each stderr line a progress line;
  - any other: the error `exit code <n>`, then on its next line a JSON object of what it wrote,
    `{"stdout": ..., "stderr": ...}`: the core answers a failed step's error without its lines.
  - Calls run side by side (kern's runner runs each step in its own thread), and each captures its
    own output (`captured`): what its thread, the threads it starts and its subprocesses write. The
    process has one working directory: calls in one directory run together, a call in another
    waits until they end (`Directory`).
- **Routed:** `routed` sends an interactive command through `call.<command>` and prints the answer
  as the command would have; `SE_KERN=off` keeps every command direct, `SE_KERN=on` refuses to fall
  back. Only interactive commands go through kern: they only read, so a call that fails on the way
  runs again directly without doing anything twice. A batch command writes, and runs directly.
  - A call kern has not answered within `CALL_WAIT` (60 s), such as one waiting behind calls in
    another directory, is given up (`call.core.abandon`): kern ends it, the component drops it
    from the directory's line where it still waits there, and the command runs directly.
- **Streamed:** a batch command its script names in `STREAMED_COMMANDS` (`integrate`) runs as one
  call through kern where kern's GitHub relay serves the checkout: its progress lines print as they
  come, the call waits as long as kern says anything (`CALL_IDLE`), and each GitHub step it needs
  is one `github.step` request (`Stepped`). A call kern refuses before it says anything runs
  directly, the file-based hand-off, and says that it fell back (`fell_back`); one that fails on
  the way is reported, never run twice.
- **Placed:** `wiring.toml` places each component with `se_components.py run <name>`, which puts
  kern's Python SDK and `scripts/` on the path and runs `python -m kern run components/<name>`.

Standard library only; kern's SDK is imported where it is needed, from `kern/python/`.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import textwrap
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

SE_ROOT = Path(__file__).resolve().parents[1]
#: Where SE's components live, under the checkout kern serves (kern/README.md "The host").
COMPONENTS = "components"
#: The switch of routed: off, on, or unset for kern where it serves this checkout.
SWITCH = "SE_KERN"
#: A call's optional first argument: the directory the command runs in.
CWD = "--se-cwd="
#: kern's standing file under the checkout it serves (kern/host/standing.go).
STANDING = Path(".se") / ".runtime" / "standing.json"
#: How long routed waits for kern to answer a call, then gives it up and runs the command directly:
#: an interactive command only reads, so a minute is long (kern's own verb wait, host.VerbWait).
CALL_WAIT = 60.0
#: How long a streamed call waits for any word from kern: kern beats every 5 s (host.CallBeat).
CALL_IDLE = 60.0
#: How long a streamed command's thread waits for the answer of one GitHub step: the github
#: component's step-wait (60 minutes), and a margin.
STEP_ANSWER_WAIT = 65 * 60.0
#: A streamed command's request port, which the wiring binds to the github component's verb step.
STEP_PORT = "step"
#: The github component's shapes of its verb step's request and answer (kern's github.StepShape).
STEP_SHAPE, STEP_ANSWER_SHAPE = "github.step", "github.step-answer"
STEP_HELP = ("One GitHub step of a streamed command through kern's relay: the tool and the input "
             "the session runs, answered with the tool's answer.")
#: How long routed waits to connect: kern stands on loopback.
CONNECT_WAIT = 0.5
REFERENCE_WIDTH = 100
#: The scripts whose commands are components, in the README's order: each defines make_parser,
#: COMPONENTS and INTERACTIVE_COMMANDS.
SCRIPTS = ("work_tickets", "review", "retro", "overhaul", "timeline", "deck", "se")
#: Who writes the declarations (work_tickets.py's `docs` and `format`).
GENERATOR = "`work_tickets.py docs`"
EXIT_ERROR = re.compile(r"\Aexit code (\d+)\n?")


def sdk() -> None:
    """Put kern's Python SDK, kern/python/ beside this script's checkout, on the path."""
    path = str(SE_ROOT / "kern" / "python")
    if path not in sys.path:
        sys.path.insert(0, path)


# Declared.

@dataclass(frozen=True)
class Declared:
    """One command as a component declares it."""

    name: str
    usage: str
    help: str
    interactive: bool
    #: It changes nothing, and this is when an agent uses it: kern's MCP door offers it. Empty
    #: for a command not declared read-only.
    mcp: str = ""


def summary(help_text: str) -> str:
    """A command's summary: its help up to the first semicolon, on one short line."""
    return textwrap.shorten(help_text.split("; ")[0], 72, placeholder=" ...")


class Group(NamedTuple):
    """One component of a script: its name, its heading in the reference, its help, and its
    commands by their words after the script's name, `backlog file` for a subcommand."""

    name: str
    title: str
    help: str
    commands: tuple[str, ...]


def declaration(name: str, help_text: str, group: str, commands: Iterable[Declared],
                generator: str, source: str = "its command registry", steps: bool = False) -> str:
    """The text of the component.toml of one command group, as `generator` writes it from
    `source`; with `steps`, the request port its streamed commands ask GitHub steps on."""
    q = lambda value: json.dumps(value, ensure_ascii=False)  # a TOML basic string  # noqa: E731
    lines = [f"# Generated by {generator} from {source}; change a command there.",
             f"name = {q(name)}", "contract = 1", f"help = {q(help_text)}"]
    for c in commands:
        lines += ["", f"[commands.{q(c.name)}]", f"usage = {q(c.usage)}",
                  f"summary = {q(summary(c.help))}", f"group = {q(group)}", f"help = {q(c.help)}",
                  f"class = {q('interactive' if c.interactive else 'batch')}"]
        if c.mcp:
            lines += ["read-only = true", f"mcp = {q(c.mcp)}"]
    if steps:
        lines += ["", f"[requests.{STEP_PORT}]", f"type = {q(STEP_SHAPE)}",
                  f"answer = {q(STEP_ANSWER_SHAPE)}",
                  f"help = {q(STEP_HELP)}"]
    return "\n".join(lines) + "\n"


def leaves(parser: argparse.ArgumentParser, words: tuple[str, ...] = ()
           ) -> list[tuple[tuple[str, ...], str, argparse.ArgumentParser]]:
    """Every command of an argparse parser that has no subcommands: its words after the program,
    its help (from add_parser's help=) and its parser, in the order they were added."""
    found = []
    for action in parser._actions:  # argparse offers no public walk of its subparsers
        if not isinstance(action, argparse._SubParsersAction):
            continue
        helps = {choice.dest: choice.help or "" for choice in action._choices_actions}
        for name, sub in action.choices.items():
            below = leaves(sub, (*words, name))
            found += below or [((*words, name), helps.get(name, ""), sub)]
    return found


def usage(prog: str, parser: argparse.ArgumentParser, width: int = REFERENCE_WIDTH) -> str:
    """A command's usage as argparse prints it under the program name `prog`, without its
    "usage: " prefix and without -h."""
    formatter = argparse.HelpFormatter(prog, width=width)
    formatter.add_usage(None, [a for a in parser._actions if not isinstance(a, argparse._HelpAction)],
                        parser._mutually_exclusive_groups)
    # Without argparse's "usage: " prefix, its continuation lines move left by as much.
    return "\n".join(line[len("usage: "):] for line in formatter.format_help().rstrip().splitlines())


def declared(parser: argparse.ArgumentParser, groups: Iterable[Group],
             interactive: Iterable[str] = (), read_only: Mapping[str, str] | None = None
             ) -> dict[str, tuple[Group, list[Declared]]]:
    """Each group with its commands by the group's name, read from the script's argparse parser:
    every command the parser runs belongs to exactly one group. A parser without subcommands is one
    command, the script itself, which a group names as `""`, its help the parser's description. A
    command named in `interactive` only reads (class interactive); every other is batch. A command
    named in `read_only` changes nothing, and maps to its MCP description, which it needs."""
    script = parser.prog
    found = {" ".join(words): (words, help_text, sub) for words, help_text, sub in
             leaves(parser) or [((), parser.description or "", parser)]}
    groups = list(groups)
    grouped = [name for group in groups for name in group.commands]
    if sorted(grouped) != sorted(found):
        missing, extra = sorted(set(found) - set(grouped)), sorted(set(grouped) - set(found))
        raise ValueError(f"{script}: its components' commands differ from its parser: missing "
                         f"{missing}, unknown {extra}")
    interactive, read_only = frozenset(interactive), dict(read_only or {})
    unknown = sorted(set(read_only) - set(found))
    undescribed = sorted(n for n, text in read_only.items() if not str(text).strip())
    if unknown or undescribed:
        raise ValueError(f"{script}: READ_ONLY_COMMANDS names commands its parser lacks {unknown}, "
                         f"and commands without an MCP description {undescribed}: say when an "
                         "agent uses each")
    return {group.name: (group, [Declared(" ".join((script, *found[n][0])),
                                          usage(" ".join((script, *found[n][0])), found[n][2]),
                                          found[n][1], n in interactive, read_only.get(n, ""))
                                 for n in group.commands])
            for group in groups}


def declarations(parser: argparse.ArgumentParser, groups: Iterable[Group],
                 interactive: Iterable[str] = (), source: str | None = None,
                 streamed: Iterable[str] = (), read_only: Mapping[str, str] | None = None
                 ) -> dict[str, str]:
    """Each group's component.toml text by its name, read from the script's argparse parser
    (`declared`). `source` names what the header says the declaration is generated from, by
    default the script's parser. A group holding a command named in `streamed` declares the
    request port `step` (`Stepped`)."""
    streamed = frozenset(streamed)
    return {name: declaration(name, group.help, group.title, commands, GENERATOR,
                              source or f"{parser.prog}'s parser",
                              steps=bool(streamed & set(group.commands)))
            for name, (group, commands) in declared(parser, groups, interactive,
                                                    read_only).items()}


#: Held while a script loads, so a call beside it in another thread never reads it half loaded.
_LOADING = threading.RLock()


def script(name: str):
    """The script `scripts/<name>.py` beside this one, as a module: the one running as __main__
    where that is it, else loaded once under its own name."""
    path = Path(__file__).resolve().with_name(f"{name}.py")
    main_module = sys.modules.get("__main__")
    if Path(getattr(main_module, "__file__", None) or "").resolve() == path:
        return main_module
    with _LOADING:
        module = sys.modules.get(name)
        if module is None:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                sys.modules.pop(name, None)
                raise
    return module


def relay_module():
    """se_relay, SE's reads and steps through kern's GitHub relay, beside this script."""
    return script("se_relay")


def components(root: Path) -> dict[Path, str]:
    """The component.toml of every component of SE's SCRIPTS under root, in the README's order. A
    component two scripts share (render: timeline.py and deck.py) holds both scripts' commands, in
    SCRIPTS' order, under the group the first one names: each later script names that same group,
    its title and help included."""
    merged: dict[str, tuple[Group, list[Declared], list[str]]] = {}
    stepped: set[str] = set()
    for name in SCRIPTS:
        module = script(name)
        parser = module.make_parser()
        source = getattr(module, "COMPONENT_SOURCE", None) or f"{parser.prog}'s parser"
        for group_name, (group, commands) in declared(
                parser, module.COMPONENTS, module.INTERACTIVE_COMMANDS,
                getattr(module, "READ_ONLY_COMMANDS", None)).items():
            if group_name not in merged:
                merged[group_name] = (group, [], [])
            first, into, sources = merged[group_name]
            if (first.title, first.help) != (group.title, group.help):
                raise ValueError(f"{parser.prog}: component {group_name} differs in its title or "
                                 "help from the script that names it first")
            into += commands
            sources.append(source)
            if set(getattr(module, "STREAMED_COMMANDS", ())) & set(group.commands):
                stepped.add(group_name)
    return {root / COMPONENTS / group_name / "component.toml":
            declaration(group_name, group.help, group.title, commands, GENERATOR,
                        " and ".join(sources), steps=group_name in stepped)
            for group_name, (group, commands, sources) in merged.items()}


def component_names() -> list[str]:
    """The names of every component of SE's SCRIPTS, in the README's order, each once."""
    return list(dict.fromkeys(group.name for name in SCRIPTS for group in script(name).COMPONENTS))


def catalog(root: Path, names: Iterable[str]):
    """The declarations of the named components under root, as kern reads them, in that order."""
    sdk()
    from kern import declaration as kern_declaration

    return [kern_declaration.read(root / COMPONENTS / name) for name in names]


def reference(declarations) -> str:
    """The README's command reference: per component, its help and each command's usage and help."""
    parts = []
    for d in declarations:
        group = next(iter(d.commands.values())).group if d.commands else d.name
        entries = [c.usage + "\n" + textwrap.fill(c.help, REFERENCE_WIDTH, initial_indent="    ",
                                                  subsequent_indent="    ")
                   for c in d.commands.values()]
        about = textwrap.fill(f"`{COMPONENTS}/{d.name}`: {d.help}", REFERENCE_WIDTH)
        parts.append(f"#### {group}\n\n{about}\n\n```text\n"
                     + "\n\n".join(entries) + "\n```")
    return "\n\n".join(parts)


# Attached.

class _Capture(NamedTuple):
    """One call's capture: its streams, and the files a subprocess it starts writes."""

    out: io.StringIO
    err: io.StringIO
    out_file: object
    err_file: object


_calls = threading.local()  # .capture: the capture of the call this thread runs, if any
_installed_lock = threading.Lock()
#: How many captures stand, and what the first one replaced: sys.stdout, sys.stderr,
#: subprocess.Popen.__init__ and threading.Thread.start.
_installed: dict = {"count": 0, "saved": None}


def _capture() -> _Capture | None:
    return getattr(_calls, "capture", None)


class _Stream(io.TextIOBase):
    """sys.stdout or sys.stderr while calls capture: what a thread writes goes to its own call's
    capture, or, in a thread that runs no call, where it went before."""

    def __init__(self, which: str, before):
        super().__init__()
        self.which, self.before = which, before

    def _target(self):
        capture = _capture()
        return getattr(capture, self.which) if capture is not None else self.before

    def write(self, text: str) -> int:
        return self._target().write(text)

    def flush(self) -> None:
        with contextlib.suppress(Exception):
            self._target().flush()

    def fileno(self) -> int:  # a subprocess handed sys.stdout writes the call's file
        capture = _capture()
        if capture is not None:
            return getattr(capture, self.which + "_file").fileno()
        return self.before.fileno()

    def isatty(self) -> bool:
        return _capture() is None and bool(getattr(self.before, "isatty", lambda: False)())

    def __getattr__(self, name: str):
        return getattr(self.before, name)


def _install() -> None:
    """The first capture installs the per-call streams, and has each subprocess and thread a
    call starts write into that call's capture; the last one restores what stood before."""
    import subprocess

    with _installed_lock:
        _installed["count"] += 1
        if _installed["count"] > 1:
            return
        popen_init, thread_start = subprocess.Popen.__init__, threading.Thread.start

        def init(self, *args, **kwargs):
            capture = _capture()
            if capture is not None:
                if len(args) < 5 and kwargs.get("stdout") is None:
                    kwargs["stdout"] = capture.out_file
                if len(args) < 6 and kwargs.get("stderr") is None:
                    kwargs["stderr"] = capture.err_file
            popen_init(self, *args, **kwargs)

        def start(self):
            capture = _capture()
            if capture is not None:
                run = self.run

                def bound():
                    _calls.capture = capture
                    run()
                self.run = bound
            thread_start(self)

        _installed["saved"] = (sys.stdout, sys.stderr, popen_init, thread_start)
        sys.stdout, sys.stderr = _Stream("out", sys.stdout), _Stream("err", sys.stderr)
        subprocess.Popen.__init__, threading.Thread.start = init, start


def _uninstall() -> None:
    import subprocess

    with _installed_lock:
        _installed["count"] -= 1
        if _installed["count"]:
            return
        stdout, stderr, subprocess.Popen.__init__, threading.Thread.start = _installed["saved"]
        if isinstance(sys.stdout, _Stream):
            sys.stdout = stdout
        if isinstance(sys.stderr, _Stream):
            sys.stderr = stderr


@contextlib.contextmanager
def captured(err: io.StringIO | None = None) -> Iterator[tuple[io.StringIO, io.StringIO]]:
    """Capture the stdout and stderr of the call this thread runs, stderr into `err` where given:
    what it writes, what the threads it starts write, and what each subprocess it starts writes
    where that would have gone to the process's own streams. Calls in other threads capture their
    own alongside, so calls run side by side."""
    with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
        out, err = io.StringIO(), (err if err is not None else io.StringIO())
        before = _capture()
        _install()
        _calls.capture = _Capture(out, err, out_file, err_file)
        try:
            yield out, err
        finally:
            _calls.capture = before
            _uninstall()
            for into in (out_file, err_file):
                into.seek(0)
            out.write(out_file.read().decode("utf-8", "replace"))
            err.write(err_file.read().decode("utf-8", "replace"))


class GivenUp(Exception):
    """kern gave up the call this thread runs before it ran (kern's stop word, `kern.abandoned`)."""


class Directory:
    """The process's one working directory, shared by the calls it runs: calls in the same
    directory run side by side; a call in another waits until they have ended, and the process
    stands where it stood once all have. Waiting calls are served in arrival order: a call enters
    only once every call that arrived before it has, so calls in one directory never starve a call
    in another, and the calls at the head of the line that share a directory enter together. A call
    kern gives up while it waits leaves the line (`GivenUp`). A call waiting for a GitHub step lets
    go of its directory meanwhile (`released`), and takes its place at the end of the line after."""

    def __init__(self) -> None:
        self.changed = threading.Condition()
        self.waiting = 0
        self._line: list[list[str]] = []  # the waiting calls, in arrival order: [their directory]
        self._dir: str | None = None
        self._count = 0
        self._home = ""

    def _wake(self, _reason: str = "") -> None:
        with self.changed:
            self.changed.notify_all()

    def _enter(self, want: str | None, abandon=None) -> str:
        with self.changed:
            if not self._count:
                self._home = os.path.realpath(os.getcwd())
            want = os.path.realpath(want) if want else self._home
            place = [want]
            self._line.append(place)
            self.waiting += 1
            given = abandon.event.is_set if abandon is not None else (lambda: False)
            if abandon is not None:
                abandon.when(self._wake)
            self.changed.notify_all()
            try:
                self.changed.wait_for(lambda: given() or (
                    self._line[0] is place and (not self._count or self._dir == want)))
            finally:
                self.waiting -= 1
                self._line.remove(place)
                self.changed.notify_all()
            if given():
                raise GivenUp(f"kern gave the call up while it waited for {want}: {abandon.reason}")
            if not self._count:
                os.chdir(want)
                self._dir = want
            self._count += 1
            return want

    def _leave(self) -> None:
        with self.changed:
            self._count -= 1
            if not self._count:
                with contextlib.suppress(OSError):
                    os.chdir(self._home)
                self._dir = None
            self.changed.notify_all()

    @contextlib.contextmanager
    def within(self, cwd: str | None, abandon=None) -> Iterator[None]:
        """Run in `cwd`, or, without one, where the process stands; with `abandon` (kern's
        `Abandon` of the call), a call kern gives up while it waits raises `GivenUp`."""
        _calls.directory = self._enter(cwd, abandon)
        held = [True]
        _calls.abandon, _calls.held = abandon, held
        try:
            yield
        finally:
            if held[0]:
                self._leave()

    @contextlib.contextmanager
    def released(self) -> Iterator[None]:
        """Let go of this thread's call's directory while it waits, and take it back after; a call
        kern gave up meanwhile does not take it back, and raises `GivenUp`."""
        here, held = getattr(_calls, "directory", None), getattr(_calls, "held", None)
        if here is None or not held or not held[0]:
            yield
            return
        self._leave()
        held[0] = False
        try:
            yield
        finally:
            self._enter(here, getattr(_calls, "abandon", None))
            held[0] = True


#: The working directory of this process's calls.
DIRECTORY = Directory()


class Said(io.StringIO):
    """A stderr that also says each whole line as it is written."""

    def __init__(self, say: Callable[[str], None]):
        super().__init__()
        self.say, self.part = say, ""

    def write(self, text: str) -> int:
        self.part += text
        *lines, self.part = self.part.split("\n")
        for line in lines:
            self.say(line)
        return super().write(text)


def run_main(main: Callable[[list[str]], int], argv: list[str], cwd: str | None,
             say: Callable[[str], None] | None = None, abandon=None) -> tuple[int, str, str]:
    """Run a script's main in `cwd` (`DIRECTORY`): its exit code, stdout and stderr, its own call's
    alone (`captured`); with `say`, each stderr line the script writes is also said as it comes.
    With `abandon`, kern's `Abandon` of the call, a call kern gives up before it ran raises
    `GivenUp`."""
    code = 0
    with DIRECTORY.within(cwd, abandon), captured(Said(say) if say else None) as (out, err):
        try:
            code = main(argv)
        except SystemExit as stop:  # argparse's refusal or --help
            code = stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
            if not isinstance(stop.code, (int, type(None))):
                print(stop.code, file=sys.stderr)
    return code, out.getvalue(), err.getvalue()


def attach(name: str, scripts: str | Iterable[str], folder: Path):
    """The component of that name in `folder`, each declared command answered by the main of the
    script it names first (`timeline.py`, `deck.py build`), one of `scripts`."""
    sdk()
    import kern

    comp = kern.component(name, folder)
    scripts = (scripts,) if isinstance(scripts, str) else tuple(scripts)

    def stepped(module, words: list[str]):
        def run(args: list[str], inputs, say):
            cwd = None
            if args and args[0].startswith(CWD):
                cwd, args = args[0][len(CWD):], args[1:]
            return Stepped(comp, module.main, [*words, *args], cwd, say, " ".join(words)).result()
        return run

    def answer(module, words: list[str]):
        def run(args: list[str], inputs, say):
            cwd = None
            if args and args[0].startswith(CWD):
                cwd, args = args[0][len(CWD):], args[1:]
            code, out, err = run_main(module.main, [*words, *args], cwd, abandon=kern.abandoned())
            if code:  # the core answers a failed step's error alone, without its lines
                raise kern.KernError(f"exit code {code}\n" + json.dumps({"stdout": out, "stderr": err}))
            for line in err.splitlines():
                say(line)
            return out.rstrip("\n")
        return run

    for command in comp.decl.commands:
        first, *words = command.split()
        if first.removesuffix(".py") not in scripts or not first.endswith(".py"):
            raise kern.KernError(f"component {name} declares {command!r}, which "
                                 f"{' nor '.join(s + '.py' for s in scripts)} does not run")
        module = importlib.import_module(first.removesuffix(".py"))
        streamed = " ".join(words) in getattr(module, "STREAMED_COMMANDS", frozenset())
        comp.command(command)((stepped if streamed else answer)(module, words))
    return comp


# Routed.

def kern_root(start: Path) -> Path | None:
    """The checkout kern serves for `start`: the nearest folder up that holds .git."""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


def standing(root: Path) -> dict | None:
    try:
        return json.loads((root / STANDING).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def serves(root: Path, script: Path) -> bool:
    """Whether the kern serving `root` runs the commands of `script`: root holds SE's script of
    that name, whose commands its components answer. Any copy of it is routed there, the
    plugin's (the path SE's skills name) as much as the checkout's own: kern answers with the
    checkout's code, the code of what the session works on."""
    return (root / "scripts" / script.name).is_file()


def fell_back(script: Path, words: list[str], why: str) -> None:
    """Say on stderr that a streamed command runs without kern's relay, and why: its GitHub steps
    follow as the file-based hand-off, never silently."""
    print(f"se: {' '.join([script.name, *words])} fell back to the file-based hand-off: {why}",
          file=sys.stderr)


def routed(script: Path, words: list[str], argv: list[str], interactive: bool,
           streamed: bool = False) -> int | None:
    """The exit code of the command `words` run through kern, having printed its answer; None where
    it runs directly: SE_KERN=off, a batch command, no kern serving this checkout with this script
    (`serves`), or a call that failed on the way (with SE_KERN=on an error), among them one kern
    did not answer within CALL_WAIT, which it gives up first.
    A `streamed` batch command goes through kern only where kern's GitHub relay serves the
    checkout (`streamed_call`), and says so where it falls back (`fell_back`)."""
    switch = os.environ.get(SWITCH, "").lower()
    if switch == "off" and streamed and relay_module().steps() is None:  # not kern's own call
        fell_back(script, words, f"{SWITCH}=off")
    if switch == "off" or not (interactive or streamed):
        return None
    if streamed:
        answered = streamed_call(script, words, argv, switch)
        if answered is not None or not interactive:
            return answered
    root = kern_root(Path.cwd())
    found = standing(root) if root else None
    if root is None or found is None or not serves(root, script):
        if switch == "on":
            print(f"error: {SWITCH}=on: no kern serves {Path.cwd()} with this {script.name}",
                  file=sys.stderr)
            return 1
        return None
    sdk()
    from kern.nats import NatsError, Peer
    from kern.subjects import token

    name = " ".join([script.name, *words])
    try:
        peer = Peer(found["bus"], "client", found["users"]["client"], name="se", timeout=CONNECT_WAIT)
        try:
            answer = peer.request("call." + token(name), {"args": [CWD + os.getcwd(), *argv]},
                                  CALL_WAIT, give_up=True).json() or {}
        finally:
            peer.close()
    except (NatsError, OSError, KeyError, TypeError, ValueError) as error:
        if switch == "on":
            print(f"error: {SWITCH}=on: kern's call of {name} failed: {error}", file=sys.stderr)
            return 1
        return None
    failed = str(answer.get("error") or "")
    exit_ = EXIT_ERROR.match(failed)
    if failed and not exit_:  # kern refused the call: no such command, no attach, a timeout
        if switch == "on":
            print(f"error: {SWITCH}=on: kern: {failed}", file=sys.stderr)
            return 1
        return None
    if exit_:
        said = json.loads(failed[exit_.end():] or "{}")
        sys.stderr.write(said.get("stderr", ""))
        sys.stdout.write(said.get("stdout", ""))
        return int(exit_.group(1))
    for line in answer.get("lines") or []:
        print(line, file=sys.stderr)
    text = str(answer.get("text") or "")
    if text:
        print(text)
    return 0


def streamed_call(script: Path, words: list[str], argv: list[str], switch: str) -> int | None:
    """Run a streamed batch command as one call through kern where kern's GitHub relay serves this
    checkout: each progress line prints on stderr as kern streams it, the call waits as long as
    kern says anything within CALL_IDLE, and the answer prints as the command would have. None,
    and the command runs directly (its file-based hand-off), where no relay serves or kern refuses
    the call before saying anything; a call that fails after it began is an error, never rerun.
    Each None says why on stderr (`fell_back`)."""
    root = kern_root(Path.cwd())
    if root is None or not serves(root, script):
        fell_back(script, words, f"no kern serves {Path.cwd()} with SE's {script.name}")
        return None
    if relay_module().relay(root) is None:
        fell_back(script, words, f"no kern serves {root} with its GitHub component on the relay "
                                 "backend")
        return None
    found = standing(root)
    if found is None:
        fell_back(script, words, f"kern's standing file {root / STANDING} is gone")
        return None
    sdk()
    from kern.nats import NatsError, Peer
    from kern.subjects import token

    name = " ".join([script.name, *words])
    heard: list[str] = []

    def progress(msg) -> None:
        line = (msg.json() or {}).get("line")
        if line is not None:
            heard.append(str(line))
            print(line, file=sys.stderr, flush=True)

    try:
        peer = Peer(found["bus"], "client", found["users"]["client"], name="se", timeout=CONNECT_WAIT)
    except (NatsError, OSError, KeyError, TypeError, ValueError) as error:
        fell_back(script, words, f"kern's bus is not reachable: {error}")
        return None
    try:
        answer = peer.call("call." + token(name), {"args": [CWD + os.getcwd(), *argv]}, progress,
                           CALL_IDLE).json() or {}
    except (NatsError, OSError, ValueError) as error:
        print(f"error: kern's call of {name} failed after it began, so it is not run again: "
              f"{error}", file=sys.stderr)
        return 1
    finally:
        peer.close()
    failed = str(answer.get("error") or "")
    exit_ = EXIT_ERROR.match(failed)
    if failed and not exit_:
        if not heard and switch != "on":  # refused before it ran: no such command, no attach
            fell_back(script, words, f"kern refused the call: {failed}")
            return None
        print(f"error: kern: {failed}", file=sys.stderr)
        return 1
    if exit_:
        said = json.loads(failed[exit_.end():] or "{}")
        sys.stdout.write(said.get("stdout", ""))
        return int(exit_.group(1))
    text = str(answer.get("text") or "")
    if text:
        print(text)
    return 0


class Stepped:
    """A streamed command in the component's process: the script's main runs in a thread of its
    own, with se_relay's step set, and each GitHub step it asks becomes one request on the
    command's `step` port, which the wiring binds to the github component's verb step; the
    answer comes back through the request's continuation (kern's Requests and Then). Its stderr
    lines are said as they come. Calls run side by side, each its own thread and capture; while
    one waits for a step's answer it lets go of the working directory (`Directory.released`).
    Where kern gives the call up (its stop word, `kern.abandoned`), the step waiting for an answer
    fails at once, and so does each step the command asks after, so its thread ends;
    `STEP_ANSWER_WAIT` only bounds a wait kern never ends."""

    def __init__(self, comp, main: Callable[[list[str]], int], argv: list[str], cwd: str | None,
                 say: Callable[[str], None], key: str):
        import queue

        import kern

        self.comp, self.say, self.key = comp, say, key
        self.out: queue.Queue = queue.Queue()  # ("ask", value) or ("done", (code, out, err))
        self.answers: queue.Queue = queue.Queue()
        self.abandon = kern.abandoned()  # the call this step thread runs
        self.abandon.when(lambda reason: self.answers.put(("stop", f"kern gave it up: {reason}")))
        threading.Thread(target=self._run, args=(main, argv, cwd), daemon=True,
                         name=f"se-stepped-{key}").start()

    def step(self, tool: str, input_: dict, note: str, wait: str) -> object:
        """Ask one GitHub step from the command's thread; the tool's answer."""
        import queue

        if self.abandon.event.is_set():
            raise RuntimeError(f"the call through kern stopped: kern gave it up: {self.abandon.reason}")
        ask = {"tool": tool, "input": input_, **({"note": note} if note else {}),
               **({"wait": wait} if wait else {})}
        self.out.put(("ask", ask))
        try:
            with DIRECTORY.released():
                kind, value = self.answers.get(timeout=STEP_ANSWER_WAIT)
        except queue.Empty:
            kind, value = "stop", f"no answer to the step {tool} within {STEP_ANSWER_WAIT:.0f} s"
        except GivenUp:
            kind, value = "stop", f"kern gave it up: {self.abandon.reason}"
        if kind == "stop":
            raise RuntimeError(f"the call through kern stopped: {value}")
        return value.get("data") if isinstance(value, dict) else value

    def _run(self, main, argv, cwd) -> None:
        try:
            with relay_module().stepping(self.step):
                done = run_main(main, argv, cwd, self.say, self.abandon)
        except BaseException as error:  # noqa: BLE001 - the command's thread reports, never dies
            done = (1, "", f"{error}\n")
        self.out.put(("done", done))

    def result(self):
        """The next step's answer for kern: a request, with its continuation, or the end."""
        import kern

        kind, value = self.out.get()
        if kind == "ask":
            def then(answers: list) -> object:
                self.answers.put(("answer", answers[0] if answers else None))
                return self.result()
            return self.comp.result(requests=[self.comp.ask(STEP_PORT, value)], then=then)
        code, out, err = value
        if code:
            raise kern.KernError(f"exit code {code}\n" + json.dumps({"stdout": out, "stderr": err}))
        return out.rstrip("\n")


# Placed.

def main(argv: list[str] | None = None) -> int:
    """`se_components.py run <name>`: the process of SE's component <name>, as wiring.toml places it;
    `run-adhoc <name>` runs an ad hoc component under .se/components/<name>, as the ad hoc wiring
    overlay places it (se_component.py)."""
    args = sys.argv[1:] if argv is None else argv
    folders = {"run": SE_ROOT / COMPONENTS, "run-adhoc": SE_ROOT / ".se" / COMPONENTS}
    if len(args) != 2 or args[0] not in folders:
        print("usage: se_components.py (run | run-adhoc) <component>", file=sys.stderr)
        return 2
    os.environ[SWITCH] = "off"  # the component runs each command directly
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sdk()
    from kern import runner

    return runner.main(["run", str(folders[args[0]] / args[1])])


if __name__ == "__main__":
    raise SystemExit(main())
