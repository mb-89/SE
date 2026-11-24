# se:template se/python-module 1.0.0
"""`se component add <name>`: scaffold an ad hoc component (docs/go-core.md "Scripts are ad hoc,
components are long-term").

An ad hoc component is a Python component over NATS that lives under the ignored `.se/components/`,
so it is never tracked. `add` writes its `component.toml` and `__init__.py` through SE's code
template `python-component` (`scaffolded`, docs/templates.md "Code templates"), places it in the ad hoc
wiring overlay `.se/wiring.toml` that the core reads after `wiring.toml`, and prints the one step
left: restart the core, which picks it up in about 30 ms. What keeps being used is promoted to a
tracked component under `components/` (retro.py collect names the candidates).

Standard library only.
"""

from __future__ import annotations

import re
from pathlib import Path

#: An ad hoc component's name: lower-case letters, digits and dashes, a letter first.
NAME = re.compile(r"[a-z][a-z0-9-]*\Z")

#: Where ad hoc components live, and the overlay wiring that places them; `.se/` is git-ignored.
COMPONENTS = Path(".se") / "components"
OVERLAY = Path(".se") / "wiring.toml"

#: The placement command: SE's Python runner (se_components.py) puts kern's SDK on the path and runs
#: the ad hoc component's process, as the tracked components' wiring does for SE's own.
COMMAND = ["uv", "run", "--no-project", "--python", ">=3.11", "python",
           "scripts/se_components.py", "run-adhoc"]


class ComponentError(Exception):
    """Why an ad hoc component could not be scaffolded."""


#: The code template the scaffold renders, SE's own (templates/python-component.md).
TEMPLATE = "python-component"


def scaffolded(name: str) -> dict[str, str]:
    """The component's files, by name, as the code template TEMPLATE scaffolds them for `name`:
    its component.toml, one command offered to the agent, and its __init__.py answering it."""
    import templates  # the engine loads late: only a scaffold needs it

    made = templates.scaffold(templates.own(TEMPLATE), COMPONENTS / name,
                              f"An ad hoc component: say what {name} does.", name)
    return {path.name: text for path, text in made.items()}


def instance_block(name: str) -> str:
    """The overlay wiring's instance for the ad hoc component: it is placed in its own process."""
    words = ", ".join(f'"{w}"' for w in [*COMMAND, name])
    return (f'[instances."{name}"]\n'
            f'component = "{name}"\n'
            f'command = [{words}]\n')


def add(root: Path, name: str) -> list[str]:
    """Scaffold the ad hoc component `name` in the checkout `root`; the lines to print."""
    if not NAME.fullmatch(name):
        raise ComponentError(f"{name!r} is no component name: lower-case letters, digits and "
                             "dashes, a letter first")
    folder = root / COMPONENTS / name
    if folder.exists():
        raise ComponentError(f"{folder} already exists: an ad hoc component {name} is already here")
    files = scaffolded(name)
    folder.mkdir(parents=True)
    for file, text in files.items():
        (folder / file).write_text(text, encoding="utf-8", newline="\n")

    overlay = root / OVERLAY
    block = instance_block(name)
    if overlay.exists():
        text = overlay.read_text(encoding="utf-8")
        if re.search(rf'(?m)^\[instances\."?{re.escape(name)}"?\]', text):
            raise ComponentError(f"{overlay} already places an instance {name}")
        overlay.write_text(text.rstrip("\n") + "\n\n" + block, encoding="utf-8", newline="\n")
    else:
        header = ("# Ad hoc components' wiring, read after wiring.toml (kern/index/wiring.go Merge).\n"
                  "# `se component add` writes it under the ignored .se/; it is never tracked.\n\n")
        overlay.write_text(header + block, encoding="utf-8", newline="\n")

    return [f"Scaffolded the ad hoc component {name}:",
            f"  {(COMPONENTS / name / 'component.toml').as_posix()}",
            f"  {(COMPONENTS / name / '__init__.py').as_posix()}",
            f"  placed in {OVERLAY.as_posix()}",
            "Restart the core to run it (it reads the overlay at start, about 30 ms): the next "
            "session hook does, or stop a running one with `kern stop`.",
            f"Edit the files, then call it through kern. What keeps being used is promoted to a "
            f"tracked components/{name}/ (retro.py collect names the candidates)."]
