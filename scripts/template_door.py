# se:template se/python-module 1.0.0
"""The one door to SE's template engine, the Go one (`components/template`): a Python script asks it
`fill` or `check` here and keeps no engine of its own (work issue "go-template-engine-only").

Each call runs `se template <verb>` (`components/template/cli.go`) through the process door, the
request's JSON on its stdin and the answer's JSON on its stdout, the shapes the component's verbs
take on the bus (`template.fill`, `template.check`). The binary is the session's: the one its start
named (`.se/.runtime/kern.path` of SE's checkout), else `~/.se/bin/se`, else `se` on the PATH.
Where that binary is older than the verb, or there is none, the door builds the engine from SE's
own `components/` with `go run`, so a caller never falls back to a Python engine.

Tests answer it through the process door's fake (`tests/fake_processes.py` `se_template`).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import process_door

ROOT = Path(__file__).resolve().parents[1]
#: What a binary older than the verb answers on stderr (kern's cli), with exit code 2.
NO_VERB = 'no command "template"'


class TemplateDoorError(RuntimeError):
    """The engine refused the request or could not answer it: its reason, as it said it."""


def binary(root: Path = ROOT) -> str:
    """The `se` binary the door runs: the session's (`kern.path`), else `~/.se/bin/se`, else PATH's."""
    try:
        named = (root / ".se" / ".runtime" / "kern.path").read_text(encoding="utf-8").strip()
    except OSError:
        named = ""
    if named and Path(named).is_file():
        return named
    installed = Path.home() / ".se" / "bin" / "se"
    if installed.is_file():
        return str(installed)
    return shutil.which("se") or "se"


def ask(verb: str, request: dict, *, root: Path = ROOT) -> dict:
    """The engine's answer to `verb` (fill or check) of `request`, for the templates of the checkout
    `root`; TemplateDoorError with the engine's reason where it refuses or fails."""
    data = json.dumps(request)
    flags = ["--root", str(root)]
    try:
        done = process_door.run([binary(root), "template", verb, *flags], input=data,
                                capture_output=True, text=True, encoding="utf-8")
        older = done.returncode == 2 and NO_VERB in (done.stderr or "")
    except FileNotFoundError:
        older, done = True, None  # no se binary on this machine, as on a fresh CI runner
    if older and (ROOT / "components" / "go.mod").is_file():
        done = process_door.run(["go", "run", "./cmd/se", "template", verb, *flags], input=data,
                                capture_output=True, text=True, encoding="utf-8", cwd=ROOT / "components")
    if done is None:
        raise TemplateDoorError(f"no se binary answers se template {verb}, and {ROOT} holds no components/ "
                                "to build it from; install SE's binary (docs/install.md)")
    if done.returncode:
        raise TemplateDoorError((done.stderr or done.stdout or f"se template {verb} failed").strip())
    return json.loads(done.stdout)


def fill(template: str, fields: dict, raw: str = "", *, title: str | None = None, root: Path = ROOT) -> str:
    """The document the engine fills `template` with from `fields`, checked against the raw input
    `raw`; TemplateDoorError naming every finding where it refuses, and nothing made."""
    request: dict = {"template": template, "fields": fields, "raw": raw}
    if title is not None:
        request["title"] = title
    return ask("fill", request, root=root)["document"]


def check(body: str, *, template: str = "", action: str = "", title: str | None = None,
          labels: list[str] | None = None, root: Path = ROOT) -> dict:
    """The engine's check of `body` against `template`, or the one it selects for `action`: the
    template it checked against, whether something refuses, and every finding."""
    request: dict = {"template": template, "action": action, "body": body}
    if title is not None:
        request["title"] = title
    if labels:
        request["labels"] = labels
    return ask("check", request, root=root)
