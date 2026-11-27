# se:template se/python-module 1.0.0
"""The shared part of every SE script (templates/python-script.md): its help and its logging, so a
script holds only its own part. Standard library only; importing it costs no more than argparse.

- `parser(**options)`: the script's argparse parser, as `argparse.ArgumentParser(**options)` makes
  it, with LOG_HELP, how to raise the log level, after its own epilog.
- `run(main)`: the entry a script's `__main__` block calls, `raise SystemExit(se_script.run(main))`:
  it sets up logging (`configure`), logs the start and the exit code at DEBUG and answers main's
  exit code; an exception is logged with its trace at DEBUG and raised as it stands.
- `configure()`: logging on stderr at the level LEVEL_VARIABLE names (DEBUG, INFO, WARNING, ERROR),
  WARNING where it names none or no level, each line `<logger>: <LEVEL>: <message>`; a second call
  changes nothing. A script's own logger is `logging.getLogger(__name__)`.
- `loader(__file__)`: the script's `sibling(name)`, which answers the script `<name>.py` beside it:
  the one running as `__main__` where that is it, else loaded once under its own name when a
  command first needs it; one lock serves every script's, so a thread that asks while another
  loads a module waits for the whole module.
- `route(__file__, words, argv, interactive)`: the exit code of the command `words` where kern runs
  it (se_components `routed`), else None; `interactive` is the script's INTERACTIVE_COMMANDS.
- `swapped(owner, name, value)`: a context manager that sets `owner.<name>` to `value` for the
  block and restores it, as each door's `use(backend)` swaps its BACKEND for a test's fake.
- `dispatch(__file__, args, argv, interactive, refused=<error type>)`: `route` with the parsed
  command's words, else the command's own `args.run(args)`; an error of the `refused` type is
  answered as `<script>: <error>` with exit code 1, every other one raised.

These are the helpers every script once copied; `overhaul.py check` refuses a new copy.

The uv entry is the script's first line, `#!/usr/bin/env -S uv run python`, which the
python-script template holds; SE runs a script as `uv run python <se>/scripts/<name>.py`.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

#: The variable that sets the log level of every SE script, as `configure` reads it.
LEVEL_VARIABLE = "SE_LOG_LEVEL"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
DEFAULT_LEVEL = "WARNING"
FORMAT = "%(name)s: %(levelname)s: %(message)s"
#: What every script's help says of its logging.
LOG_HELP = (f"Logging: on stderr at {DEFAULT_LEVEL}; set {LEVEL_VARIABLE} to one of "
            f"{', '.join(LEVELS)} for more or less.")
#: The handler `configure` adds, so a second call adds none.
_HANDLER_NAME = "se_script"
#: The one lock of every script's `sibling` (`loader`), held by a reload (se_components `Code`) too.
LOADING = threading.RLock()


def parser(**options: object) -> argparse.ArgumentParser:
    """The script's parser: `argparse.ArgumentParser(**options)`, its epilog followed by LOG_HELP."""
    epilog = options.pop("epilog", None)
    return argparse.ArgumentParser(epilog=f"{epilog}\n\n{LOG_HELP}" if epilog else LOG_HELP,
                                   **options)  # type: ignore[arg-type]


def level(environ: dict[str, str] | os._Environ[str] | None = None) -> int:
    """The log level LEVEL_VARIABLE names in `environ` (default: the process's), else DEFAULT_LEVEL's."""
    named = (os.environ if environ is None else environ).get(LEVEL_VARIABLE, "").strip().upper()
    return getattr(logging, named if named in LEVELS else DEFAULT_LEVEL)


def configure(environ: dict[str, str] | None = None) -> None:
    """Log on stderr at `level(environ)`, once per process (the module docstring)."""
    root = logging.getLogger()
    if any(handler.get_name() == _HANDLER_NAME for handler in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(handler)
    root.setLevel(level(environ))


def run(main: Callable[[], int | None], environ: dict[str, str] | None = None) -> int:
    """Run the script's `main` with logging set up; its exit code (None is 0)."""
    configure(environ)
    log = logging.getLogger(os.path.basename(sys.argv[0]) or "se_script")
    log.debug("start: %s", " ".join(sys.argv[1:]))
    started = time.monotonic()
    try:
        code = main()
    except SystemExit as stop:
        log.debug("exit %s after %.3f s", stop.code, time.monotonic() - started)
        raise
    except BaseException:
        log.debug("failed after %.3f s", time.monotonic() - started, exc_info=True)
        raise
    code = 0 if code is None else code
    log.debug("exit %s after %.3f s", code, time.monotonic() - started)
    return code


def loader(script: str | Path) -> Callable[[str], ModuleType]:
    """The `sibling(name)` of the script at `script`: the script `<name>.py` beside it, loaded once
    under its own name (the module docstring)."""
    folder = Path(script).resolve().parent

    def sibling(name: str) -> ModuleType:
        path = folder / f"{name}.py"
        running = sys.modules.get("__main__")
        if Path(getattr(running, "__file__", None) or "").resolve() == path:
            return running
        with LOADING:
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

    return sibling


def route(script: str | Path, words: list[str], argv: list[str] | None,
          interactive: Collection[str] | bool, streamed: bool = False) -> int | None:
    """The exit code of the command `words` of `script` where kern runs it, having printed its
    answer; None where the script runs it itself (se_components `routed`). `argv` is main's (None:
    the process's), `interactive` the script's INTERACTIVE_COMMANDS or a plain answer."""
    rest = list(sys.argv[1 + len(words):] if argv is None else argv[len(words):])
    named = interactive if isinstance(interactive, bool) else " ".join(words) in interactive
    return loader(script)("se_components").routed(Path(script), words, rest, named, streamed)


def dispatch(script: str | Path, args: argparse.Namespace, argv: list[str] | None,
             interactive: Collection[str], streamed: bool = False,
             refused: type[Exception] | Callable[[], type[Exception]] | None = None) -> int:
    """Run the parsed command `args.command`: through kern where it runs it (`route`), else by its
    own `args.run(args)`. An error of the script's `refused` type (or of the type a callable gives,
    so the script loads it only then) is its answer: `<script>: <error>` on stderr, exit code 1;
    every other error is raised as it stands."""
    try:
        routed = route(script, [args.command], argv, interactive, streamed)
        return args.run(args) if routed is None else routed
    except Exception as error:
        kind = refused if refused is None or isinstance(refused, type) else refused()
        if kind is None or not isinstance(error, kind):
            raise
        print(f"{Path(script).name}: {error}", file=sys.stderr)
        return 1


@contextmanager
def swapped(owner: object, name: str, value: object) -> Iterator[object]:
    """`owner.<name>` set to `value` for the block, then restored, whatever the block raised."""
    previous = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield value
    finally:
        setattr(owner, name, previous)
