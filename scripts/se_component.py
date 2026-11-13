"""`se component add <name>`: scaffold an ad hoc component (docs/go-core.md "Scripts are ad hoc,
components are long-term").

An ad hoc component is a Python component over NATS that lives under the ignored `.se/components/`,
so it is never tracked. `add` writes its `component.toml` and `__init__.py`, places it in the ad hoc
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


def component_toml(name: str) -> str:
    """The scaffolded component.toml: one command, offered to the agent."""
    return (f'# An ad hoc component scaffolded by `se component add {name}` (SE\'s docs/go-core.md\n'
            '# "Scripts are ad hoc, components are long-term"). It lives under the ignored\n'
            '# .se/components/, so it is never tracked; edit it freely, then restart the core.\n'
            f'name = "{name}"\n'
            'contract = 1\n'
            f'help = "An ad hoc component: say what {name} does."\n'
            '\n'
            f'[commands."{name} run"]\n'
            f'usage = "{name} run [WORDS...]"\n'
            'summary = "Do the ad hoc work."\n'
            'group = "Ad hoc"\n'
            f'help = "Replace this with what {name} does; the scaffold echoes its words."\n'
            'class = "batch"\n'
            'session = true\n')


def init_py(name: str) -> str:
    """The scaffolded __init__.py: a Python component over NATS, one command answered."""
    ident = name.replace("-", "_")
    return ('"""An ad hoc component scaffolded by `se component add` (SE\'s docs/go-core.md "Scripts\n'
            'are ad hoc, components are long-term"). Add inputs, outputs, commands or verbs to\n'
            'component.toml and answer them here; kern\'s Python SDK is kern/python/kern/.\n'
            '"""\n'
            '\n'
            'from kern import component\n'
            '\n'
            f'{ident} = component("{name}")\n'
            '\n'
            '\n'
            f'@{ident}.command("{name} run")\n'
            'def run(args, inputs, say):\n'
            f'    return {ident}.result("ad hoc {name} ran: " + " ".join(args))\n')


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
    folder.mkdir(parents=True)
    (folder / "component.toml").write_text(component_toml(name), encoding="utf-8")
    (folder / "__init__.py").write_text(init_py(name), encoding="utf-8")

    overlay = root / OVERLAY
    block = instance_block(name)
    if overlay.exists():
        text = overlay.read_text(encoding="utf-8")
        if re.search(rf'(?m)^\[instances\."?{re.escape(name)}"?\]', text):
            raise ComponentError(f"{overlay} already places an instance {name}")
        overlay.write_text(text.rstrip("\n") + "\n\n" + block, encoding="utf-8")
    else:
        header = ("# Ad hoc components' wiring, read after wiring.toml (kern/index/wiring.go Merge).\n"
                  "# `se component add` writes it under the ignored .se/; it is never tracked.\n\n")
        overlay.write_text(header + block, encoding="utf-8")

    return [f"Scaffolded the ad hoc component {name}:",
            f"  {(COMPONENTS / name / 'component.toml').as_posix()}",
            f"  {(COMPONENTS / name / '__init__.py').as_posix()}",
            f"  placed in {OVERLAY.as_posix()}",
            "Restart the core to run it (it reads the overlay at start, about 30 ms): the next "
            "session hook does, or stop a running one with `kern stop`.",
            f"Edit the files, then call it through kern. What keeps being used is promoted to a "
            f"tracked components/{name}/ (retro.py collect names the candidates)."]
