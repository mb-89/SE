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

The uv entry is the script's first line, `#!/usr/bin/env -S uv run python`, which the
python-script template holds; SE runs a script as `uv run python <se>/scripts/<name>.py`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable

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
