"""The fleet's settings as the repository records them, compared with the live settings: an
advisory check, standalone, that nothing runs on its own and that never blocks a landing, a push
or a session start. This docstring owns the file's format and the check.

`fleet/settings.toml` records main's ruleset, the scheduled tasks and the cloud environment. Each
part is read live through its own door, and only `work_tickets.py settings-check` opens the doors:
gh (or a file holding the REST answer) for the ruleset, the answers of the session's
claude-code-remote tools `list_triggers` and `get_environment` as files for the rest. This module
holds no door: it reads the recorded file and compares it with the answers it is handed, so its
tests need none.

A recorded value `"unchecked: <reason>"` is never compared: it is a setting no door reads, or one
that may not be written down here (pub-001): names of environment variables only, never values.
A part whose door is missing is reported unchecked, never as a difference. The check exits 0
whatever it finds; only `--strict` makes a difference exit 1.

The comparison is pure: the recorded settings and the doors' answers in, the report's lines out.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

#: Where the repository records the fleet's settings, from the checkout's root.
SETTINGS = Path("fleet") / "settings.toml"
#: The marker of a recorded value no door reads.
UNCHECKED = "unchecked"
#: The ruleset keys the check compares, in the file's order.
RULESET_KEYS = ("required_checks", "strict", "merge_methods", "linear_history",
                "block_force_push", "block_deletion")
#: The scheduled-task keys the check compares (its name finds it).
TASK_KEYS = ("schedule", "model", "target", "enabled", "prompt")
#: The environment keys the check compares.
ENVIRONMENT_KEYS = ("name", "network", "setup_script")
#: The targets a scheduled task fires into, as the file names them.
TARGETS = ("persistent session", "new session")


class SettingsError(ValueError):
    """The settings file or a door's answer cannot be read; the message names which and why."""


@dataclass(frozen=True)
class Line:
    """One line of the report: `kind` is `same`, `difference` or `unchecked`; `where` names the
    setting (`ruleset.strict`, `scheduled_tasks."<name>".model`); `text` says what was found."""

    kind: str
    where: str
    text: str = ""

    def render(self) -> str:
        return f"{self.kind}: {self.where}" + (f": {self.text}" if self.text else "")


def load(root: Path) -> dict[str, object]:
    """The recorded settings of the checkout at `root`."""
    path = root / SETTINGS
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SettingsError(f"No fleet settings: {path} is missing")
    except tomllib.TOMLDecodeError as error:
        raise SettingsError(f"{path} is not valid TOML: {error}") from error
    for part in ("ruleset", "environment"):
        if not isinstance(data.get(part), dict):
            raise SettingsError(f"{path} has no [{part}] table")
    tasks = data.get("scheduled_tasks", [])
    if not isinstance(tasks, list) or not all(
            isinstance(task, dict) and isinstance(task.get("name"), str) for task in tasks):
        raise SettingsError(f"{path}: each [[scheduled_tasks]] needs a name")
    return data


def unchecked(value: object) -> str | None:
    """The reason of a recorded `"unchecked: <reason>"` value, else None."""
    if isinstance(value, str) and (value == UNCHECKED or value.startswith(UNCHECKED + ":")):
        return value[len(UNCHECKED) + 1:].strip() or "no door reads it"
    return None


def shown(value: object) -> str:
    """A value as one short line: booleans and lists as TOML writes them, a long text by its size."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(f'"{item}"' for item in value) + "]"
    if isinstance(value, str) and ("\n" in value or len(value) > 60):
        return f"{len(value.splitlines())} lines"
    return f'"{value}"' if isinstance(value, str) else str(value)


def text_difference(recorded: str, live: str) -> str:
    """Where two texts first differ, by line number, without quoting either."""
    mine, theirs = recorded.splitlines(), live.splitlines()
    for number, (a, b) in enumerate(zip(mine, theirs), 1):
        if a != b:
            return f"line {number} differs"
    return f"recorded {len(mine)} lines, live {len(theirs)} lines"


def compare(where: str, recorded: object, live: object) -> Line:
    """One recorded value against its live one."""
    reason = unchecked(recorded)
    if reason is not None:
        return Line("unchecked", where, reason)
    if isinstance(recorded, str) and isinstance(live, str) and "\n" in recorded + live:
        same = recorded.replace("\r\n", "\n").rstrip() == live.replace("\r\n", "\n").rstrip()
        return Line("same", where) if same else Line("difference", where,
                                                     text_difference(recorded, live))
    if isinstance(recorded, list) and isinstance(live, list):
        recorded, live = sorted(map(str, recorded)), sorted(map(str, live))
    if recorded == live:
        return Line("same", where)
    return Line("difference", where, f"recorded {shown(recorded)}, live {shown(live)}")


def live_ruleset(rules: object) -> dict[str, object]:
    """The compared keys from the rules GitHub applies to a branch, the REST answer of
    `GET repos/<owner>/<repo>/rules/branches/<branch>` (a list of rules, each with its `type`)."""
    if not isinstance(rules, list):
        raise SettingsError("The ruleset answer is not the list of rules "
                            "GET repos/<owner>/<repo>/rules/branches/<branch> gives")
    by_type: dict[str, dict[str, object]] = {}
    for rule in rules:
        if isinstance(rule, dict) and isinstance(rule.get("type"), str):
            parameters = rule.get("parameters")
            by_type.setdefault(rule["type"], parameters if isinstance(parameters, dict) else {})
    checks = by_type.get("required_status_checks", {})
    pull = by_type.get("pull_request", {})
    return {
        "required_checks": [str(check.get("context")) for check in
                            checks.get("required_status_checks") or [] if isinstance(check, dict)],
        "strict": bool(checks.get("strict_required_status_checks_policy", False)),
        "merge_methods": list(pull.get("allowed_merge_methods") or []),
        "linear_history": "required_linear_history" in by_type,
        "block_force_push": "non_fast_forward" in by_type,
        "block_deletion": "deletion" in by_type,
    }


def live_tasks(answer: object) -> tuple[list[dict[str, object]], bool]:
    """The scheduled tasks of a `list_triggers` answer, each with the compared keys, and whether
    the answer said more remain (`has_more`)."""
    items = answer.get("data") if isinstance(answer, dict) else answer
    if not isinstance(items, list):
        raise SettingsError("The scheduled tasks answer is not what list_triggers gives "
                            "(a \"data\" list)")
    tasks = []
    for item in items:
        if not isinstance(item, dict):
            continue
        derived = item.get("derived_state") if isinstance(item.get("derived_state"), dict) else {}
        tasks.append({
            "name": item.get("name"),
            "schedule": item.get("cron_expression") or item.get("run_once_at") or "",
            "model": derived.get("model") or item.get("model") or "",
            "target": TARGETS[0] if item.get("persist_session") else TARGETS[1],
            "enabled": bool(item.get("enabled")),
            "prompt": derived.get("prompt") or "",
        })
    return tasks, bool(isinstance(answer, dict) and answer.get("has_more"))


def live_environment(answer: object) -> dict[str, object]:
    """The compared keys of a `get_environment` answer; a withheld setup script stays None."""
    if not isinstance(answer, dict) or "name" not in answer:
        raise SettingsError("The environment answer is not what get_environment gives "
                            "(an object with its \"name\")")
    network = answer.get("network") if isinstance(answer.get("network"), dict) else {}
    script = answer.get("setup_script")
    if script is None and not answer.get("has_setup_script", True):
        script = ""
    return {"name": answer.get("name"), "network": network.get("type") or "",
            "setup_script": script}


def ruleset_lines(recorded: dict[str, object], rules: object | None, missing: str) -> list[Line]:
    if rules is None:
        return [Line("unchecked", "ruleset", missing)]
    live = live_ruleset(rules)
    return [compare(f"ruleset.{key}", recorded[key], live[key]) for key in RULESET_KEYS
            if key in recorded]


def task_lines(recorded: list[dict[str, object]], answer: object | None, missing: str
               ) -> list[Line]:
    if not recorded:
        return []
    if answer is None:
        return [Line("unchecked", "scheduled_tasks", missing)]
    live, more = live_tasks(answer)
    lines = []
    for task in recorded:
        where = f'scheduled_tasks."{task["name"]}"'
        found = [item for item in live if item["name"] == task["name"]]
        if not found:
            lines.append(Line("unchecked", where, "not in the first page list_triggers gave "
                                                  "(has_more)") if more else
                         Line("difference", where, "recorded, not live"))
            continue
        if len(found) > 1:
            lines.append(Line("difference", where, f"{len(found)} live tasks carry this name"))
        lines += [compare(f"{where}.{key}", task[key], found[0][key]) for key in TASK_KEYS
                  if key in task]
    return lines


def environment_lines(recorded: dict[str, object], answer: object | None, missing: str
                      ) -> list[Line]:
    if answer is None:
        return [Line("unchecked", "environment", missing)]
    live = live_environment(answer)
    lines = []
    for key in ENVIRONMENT_KEYS:
        if key not in recorded:
            continue
        if live[key] is None and unchecked(recorded[key]) is None:
            lines.append(Line("unchecked", f"environment.{key}", "get_environment withheld it"))
        else:
            lines.append(compare(f"environment.{key}", recorded[key], live[key]))
    return lines


def check(settings: dict[str, object], ruleset: tuple[object | None, str],
          tasks: tuple[object | None, str], environment: tuple[object | None, str]
          ) -> list[Line]:
    """Every line of the report: each door's answer (None where the door is missing) with the
    reason shown for a missing one."""
    return [*ruleset_lines(settings["ruleset"], *ruleset),
            *task_lines(settings.get("scheduled_tasks", []), *tasks),
            *environment_lines(settings["environment"], *environment)]


def report(lines: list[Line]) -> str:
    """The report: each difference and unchecked setting in one line, then the verdict."""
    counts = {kind: sum(line.kind == kind for line in lines)
              for kind in ("same", "difference", "unchecked")}
    shown_lines = [line.render() for line in lines if line.kind != "same"]
    checked = counts["same"] + counts["difference"]
    verdict = (f"{counts['difference']} difference(s)" if counts["difference"] else
               "no difference") + f" in {checked} checked settings, {counts['unchecked']} unchecked"
    return "\n".join([*shown_lines, verdict])
