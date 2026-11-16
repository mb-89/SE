"""SE under GitHub Copilot (docs/copilot.md): the opt-in install into another repository, the
self-test that needs no Copilot, and the verdict over a Copilot smoke run's JSON lines.

    copilot.py install --repo <repo> [--no-sync]
    copilot.py self-test [--build] [--cli <copilot>] [--keep]
    copilot.py smoke-verdict <json lines> [--exit-code <n>]

`install` is what `scripts/setup.sh <repo> --copilot` (and `setup.ps1 -Repo <repo> -Copilot`) runs
after the hooks: it merges SE's marketplace and plugin into the repository's
`.github/copilot/settings.json`, keeping every other key; pins `[modules.se]` in its `se.toml` as a
version range, keeping an existing pin; ignores `.se/` in git; and runs `se_modules.py sync se`.

`self-test` installs this SE, as a plugin install copies it, beside an empty project folder that is
not SE, and checks there what needs no Copilot: the generated layout, the hook registrations, the
MCP door's launcher, and the door started as Copilot starts a plugin's server (in the plugin folder,
its parent in the project), once with COPILOT_SESSION_CWD and once without, each with its handshake
and one status call that must name the project; and, where a Copilot CLI is at hand,
what that CLI reads of the plugin without signing in. It cleans up after itself. Exit code 0 every
check passed, 1 one failed.

`smoke-verdict` reads the JSON lines `copilot -p ... --output-format json` wrote
(scripts/copilot_smoke.sh) and passes where they hold SE's greeting and one answered call of an
`se` tool. Exit code 0 passed, 1 failed.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

import git_door  # noqa: E402
import se_home  # noqa: E402
import se_plugin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = PurePosixPath(".github/copilot/settings.json")
# The plugin key `<plugin>@<marketplace>` Copilot reads: the marketplace se_plugin.py generates
# (.claude-plugin/marketplace.json) is named after the plugin, so the key is `se@se`. The repository
# it lives in is SE's home, from this checkout's origin (scripts/se_home.py): no file names it.
MARKETPLACE_NAME = se_plugin.PLUGIN
PLUGIN_KEY = f"{se_plugin.PLUGIN}@{MARKETPLACE_NAME}"
IGNORED = ".se/"


class InstallError(Exception):
    """A file the install cannot merge into; the message names it and nothing is written."""


def home() -> se_home.Home:
    """SE's home, from the origin of the checkout this script runs from; InstallError without one."""
    try:
        return se_home.home(ROOT)
    except se_home.NoHome as error:
        raise InstallError(f"{error}; install SE from a clone of the repository it lives in") from error


def marketplace_source(found: se_home.Home) -> dict:
    """The marketplace source Copilot reads for SE's home: a GitHub repository by `<owner>/<repo>`,
    any other host by its clone URL."""
    if found.host == se_home.GITHUB:
        return {"source": "github", "repo": found.tracker}
    return {"source": "git", "url": f"{found.url}.git"}


def settings(existing: dict | None = None, found: se_home.Home | None = None) -> dict:
    """`existing` with SE's marketplace and plugin merged in: every other key kept, `se`'s own
    entries set."""
    found = found or home()
    data = dict(existing or {})
    for key in ("extraKnownMarketplaces", "enabledPlugins"):
        if not isinstance(data.get(key, {}), dict):
            raise InstallError(f"{SETTINGS}: `{key}` is no object")
    data["extraKnownMarketplaces"] = {**data.get("extraKnownMarketplaces", {}),
                                      MARKETPLACE_NAME: {"source": marketplace_source(found)}}
    data["enabledPlugins"] = {**data.get("enabledPlugins", {}), PLUGIN_KEY: True}
    return data


def merge_settings(repo: Path, found: se_home.Home | None = None) -> str:
    found = found or home()
    path = repo / SETTINGS
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise InstallError(f"{path}: cannot read it as JSON ({error}); fix or remove it, then "
                               "run the install again") from error
        if not isinstance(existing, dict):
            raise InstallError(f"{path}: holds no JSON object")
    merged = settings(existing, found)
    if merged == existing:
        return f"{SETTINGS}: already enables {PLUGIN_KEY}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return f"{SETTINGS}: enables {PLUGIN_KEY} from the marketplace {found.tracker}"


def version_range(root: Path = ROOT) -> str:
    """The range a repository pins SE at: this SE's major and minor version, `^MAJOR.MINOR`, so the
    public check's one-se-version rule admits the SE that installed it."""
    with (root / "se.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    major, minor = version.split(".")[:2]
    return f"^{major}.{minor}"


def pin_se(repo: Path, wanted: str, found: se_home.Home | None = None) -> str:
    path = repo / "se.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        modules = tomllib.loads(text).get("modules", {})
    except tomllib.TOMLDecodeError as error:
        raise InstallError(f"{path}: cannot read it as TOML ({error})") from error
    if isinstance(modules, dict) and "se" in modules:
        return "se.toml: keeps its [modules.se] pin"
    block = f'[modules.se]\nurl = "{(found or home()).url}.git"\nversion = "{wanted}"\n'
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + ("\n" if text else "") + block, encoding="utf-8")
    return f"se.toml: pins [modules.se] at version {wanted}"


def ignore_se(repo: Path) -> str:
    path = repo / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if {".se", ".se/", "/.se", "/.se/"} & {line.strip() for line in text.splitlines()}:
        return ".gitignore: already ignores .se/"
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + IGNORED + "\n", encoding="utf-8")
    return ".gitignore: ignores .se/"


def sync(repo: Path) -> int:
    """`se_modules.py --root <repo> sync se`: SE's module clone at the pin, in `<repo>/.se/modules/se`."""
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "se_modules.py"), "--root", str(repo),
                           "sync", "se"], check=False).returncode


def install(repo: Path, run_sync=sync) -> int:
    repo = repo.resolve()
    if repo == ROOT.resolve():
        print("copilot install: SE's own checkout needs nothing installed (docs/copilot.md, \"Install\")")
        return 0
    try:
        found = home()
        for line in (merge_settings(repo, found), pin_se(repo, version_range(), found), ignore_se(repo)):
            print(f"copilot install: {line}")
    except InstallError as error:
        print(f"copilot install: error: {error}", file=sys.stderr)
        return 2
    if run_sync is None:
        return 0
    code = run_sync(repo)
    if code:
        print(f"copilot install: error: se_modules.py sync se failed (exit code {code}); run "
              f"`uv run python {ROOT.as_posix()}/scripts/se_modules.py --root {repo.as_posix()} sync se` "
              "once the cause is fixed", file=sys.stderr)
    return 1 if code else 0


# --- self-test ------------------------------------------------------------------------------------

# What a plugin install copies is the repository's tree; the self-test copies the working tree
# without what git ignores or no install carries.
NOT_COPIED = shutil.ignore_patterns(".git", ".venv", ".se", "__pycache__", "*.pyc", ".pytest_cache",
                                    "node_modules", ".public-check.local")
AGENTS = ("se", "integrator", "reviewer", "worker")
SKILLS = ("catch-up", "decision", "work-model")
HOOK_EVENTS = {"SessionStart": "scripts/bootstrap.sh", "Stop": "scripts/se_hook.sh"}
CALL_SECONDS = 30.0  # how long the door may answer `starting` before the self-test gives up


@dataclass
class Report:
    lines: list[str]

    def add(self, outcome: str, check: str, detail: str) -> None:
        line = f"{outcome} {check}: {detail}"
        self.lines.append(line)
        print(line, flush=True)

    def count(self, outcome: str) -> int:
        return sum(line.startswith(outcome + " ") for line in self.lines)


def _json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_layout(plugin: Path, report: Report) -> None:
    """The Copilot manifest names the Copilot layout, it holds SE's agents and skills, and the copy
    matches its sources (`se_plugin.py check` of the copy)."""
    manifest = _json_file(plugin / se_plugin.COPILOT_MANIFEST)
    agents, skills = plugin / manifest["agents"], plugin / manifest["skills"]
    missing = [name for name in AGENTS if not (agents / f"{name}.agent.md").is_file()]
    missing += [name for name in SKILLS if not (skills / name / "SKILL.md").is_file()]
    if missing:
        report.add("failed", "layout", f"{se_plugin.COPILOT_MANIFEST} lacks {', '.join(missing)}")
        return
    done = subprocess.run([sys.executable, str(plugin / "scripts" / "se_plugin.py"), "check"],
                          capture_output=True, text=True, check=False)
    if done.returncode:
        report.add("failed", "layout", (done.stderr or done.stdout).strip().splitlines()[-1])
        return
    report.add("passed", "layout", f"{se_plugin.COPILOT_MANIFEST} names {manifest['agents']} "
               f"({len(AGENTS)} agents) and {manifest['skills']} ({len(SKILLS)} skills); "
               f"{done.stdout.strip()}")


def check_hooks(plugin: Path, report: Report) -> None:
    """Copilot's hooks file registers SessionStart and Stop, each a fail-open command of a script the
    plugin carries, for the host `copilot`."""
    manifest = _json_file(plugin / se_plugin.COPILOT_MANIFEST)
    hooks = _json_file(plugin / manifest["hooks"]).get("hooks", {})
    problems = []
    for event, script in HOOK_EVENTS.items():
        entries = hooks.get(event, [])
        if len(entries) != 1:
            problems.append(f"{event} has {len(entries)} entries")
            continue
        entry = entries[0]
        if script not in entry.get("bash", "") or "|| true" not in entry.get("bash", ""):
            problems.append(f"{event}'s bash command is not `bash {script} ... || true`")
        if script not in entry.get("powershell", "") or "exit 0" not in entry.get("powershell", ""):
            problems.append(f"{event}'s powershell command does not run {script} and exit 0")
        if entry.get("env", {}).get("SE_HOOK_HOST") != "copilot":
            problems.append(f"{event} does not set SE_HOOK_HOST=copilot")
        if not (plugin / script).is_file():
            problems.append(f"{script} is not in the plugin")
    if problems:
        report.add("failed", "hooks", "; ".join(problems))
    else:
        report.add("passed", "hooks", f"{manifest['hooks']} registers "
                   + ", ".join(f"{event} -> {script}" for event, script in HOOK_EVENTS.items())
                   + ", fail-open, SE_HOOK_HOST=copilot")


# The door's parent as Copilot is one: a process in the project folder (the session's working
# directory) that starts the plugin's server in the plugin folder and waits for it. The launcher reads
# its parent's working directory on Linux and macOS (scripts/se_mcp.sh).
PARENT = "import subprocess, sys; sys.exit(subprocess.call(sys.argv[2:], cwd=sys.argv[1]))"
# What a Copilot session's environment may carry that a run of the door must not inherit: each run
# sets only what it needs.
DROPPED = ("CLAUDE_PROJECT_DIR", "SE_SESSION_CWD", "PLUGIN_ROOT")
SESSION_CWD = "COPILOT_SESSION_CWD"
ROOT_IN = re.compile(r"\b(?:running|runs) in (?P<root>.+?)(?:, |$)")


def clean_env(env: dict[str, str]) -> dict[str, str]:
    """`env` without CLAUDE_PROJECT_DIR, SE_SESSION_CWD, PLUGIN_ROOT and every COPILOT_* variable."""
    return {key: value for key, value in env.items()
            if key not in DROPPED and not key.startswith("COPILOT_")}


def door_env(server: dict, plugin: Path, base: dict[str, str], session_cwd: Path | None) -> dict[str, str]:
    """The door's environment as Copilot gives it: `base`, PLUGIN_ROOT the plugin folder,
    COPILOT_SESSION_CWD where the run names one, and the manifest's `env` with each `${NAME}`
    expanded from those; an entry whose variable is unset is left out."""
    env = {**base, "PLUGIN_ROOT": str(plugin)}
    if session_cwd is not None:
        env[SESSION_CWD] = str(session_cwd)
    for key, value in server.get("env", {}).items():
        names = re.findall(r"\$\{(\w+)\}", value)
        if all(name in env for name in names):
            env[key] = re.sub(r"\$\{(\w+)\}", lambda match: env[match[1]], value)
    return env


def _folder(text: str) -> str:
    """A folder as a comparable string: resolved, Git Bash's `/c/...` read as `C:/...` on Windows,
    case folded where the platform folds it."""
    if os.name == "nt":
        drive = re.match(r"^/([A-Za-z])(/.*)?$", text)
        if drive:
            text = f"{drive[1]}:{drive[2] or '/'}"
    return os.path.normcase(str(Path(text).resolve()))


def root_verdict(text: str, project: Path) -> tuple[str, str]:
    """The outcome of one `status` answer: `passed` where it says the core runs in the project,
    `noted` naming the root it got where it names another folder (docs/copilot.md, the open point),
    `failed` otherwise."""
    first = text.splitlines()[0] if text else ""
    found = ROOT_IN.search(first)
    if found is None:
        return "failed", first or "no answer"
    if _folder(found["root"]) != _folder(str(project)):
        return "noted", (f"the door serves {found['root']}, not the project {project}: the open point "
                         f"(docs/copilot.md); {first}")
    return ("passed" if first.startswith("se: running") else "failed"), first


class Door:
    """The MCP door as Copilot spawns a plugin's server: its command in the plugin folder, started by
    a parent process in the project folder."""

    def __init__(self, command: list[str], cwd: Path, env: dict[str, str], parent_cwd: Path | None = None) -> None:
        if parent_cwd is not None:
            command, cwd = [sys.executable, "-c", PARENT, str(cwd), *command], parent_cwd
        self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, encoding="utf-8", bufsize=1)
        self.lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 0

    def _read(self) -> None:
        for line in self.process.stdout:
            self.lines.put(line)

    def send(self, method: str, params: dict | None = None, notify: bool = False) -> dict | None:
        message = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notify:
            self.next_id += 1
            message["id"] = self.next_id
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        if notify:
            return None
        deadline = time.monotonic() + CALL_SECONDS
        while time.monotonic() < deadline:
            try:
                answer = json.loads(self.lines.get(timeout=max(0.1, deadline - time.monotonic())))
            except queue.Empty:
                break
            if answer.get("id") == message["id"]:
                return answer
        raise TimeoutError(f"no answer to {method} in {CALL_SECONDS:.0f} s")

    def close(self) -> None:
        try:
            self.process.stdin.close()
            self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait()


def _text(result: dict) -> str:
    return " ".join(part.get("text", "") for part in result.get("content", []) if isinstance(part, dict))


RUNS = ((f"status-with-{SESSION_CWD}", True), ("status-from-parent-cwd", False))


def check_door(plugin: Path, project: Path, env: dict[str, str], report: Report) -> list[str]:
    """The launcher, then the door started as Copilot starts a plugin's server, once with
    COPILOT_SESSION_CWD naming the project and once without: its handshake, its tool list and one
    call of `status` each, which passes only where it names the project. Answers the roots the
    status calls named, for the cores to stop."""
    server = _json_file(plugin / se_plugin.COPILOT_MANIFEST)["mcpServers"][se_plugin.MCP_SERVER]
    command = [server["command"]] + [arg.replace(se_plugin.COPILOT_PLUGIN_ROOT, plugin.as_posix())
                                     for arg in server["args"]]
    launcher = plugin / se_plugin.LAUNCHER
    if not launcher.is_file():
        report.add("failed", "launcher", f"{se_plugin.LAUNCHER} is not in the plugin")
        return []
    report.add("passed", "launcher", f"the manifest runs `{' '.join(server['args'])}` with "
               f"{se_plugin.COPILOT_PLUGIN_ROOT} = the plugin folder, in the plugin folder, its parent "
               "in the project folder")
    roots = []
    for number, (check, with_cwd) in enumerate(RUNS):
        run_env = door_env(server, plugin, env, project if with_cwd else None)
        root = run_door(Door(command, plugin, run_env, parent_cwd=project), project, check, report,
                        quiet=number > 0)
        if root:
            roots.append(root)
    return roots


def run_door(door: Door, project: Path, check: str, report: Report, quiet: bool) -> str | None:
    """One run of the door: the handshake and tool list (reported unless `quiet`, failures always)
    and one `status` call, judged by root_verdict. Answers the root it named."""
    try:
        started = time.monotonic()
        hello = door.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                         "clientInfo": {"name": "se-copilot-self-test", "version": "1"}})
        door.send("notifications/initialized", notify=True)
        result = hello.get("result", {})
        instructions = result.get("instructions", "")
        if "error" in hello or instructions.startswith("not-installed"):
            report.add("failed", "handshake", f"{check}: {instructions or json.dumps(hello.get('error'))}")
            return None
        if not quiet:
            report.add("passed", "handshake", f"initialize answered in {time.monotonic() - started:.2f} s, "
                       f"protocol {result.get('protocolVersion')}, server "
                       f"{result.get('serverInfo', {}).get('name')} {result.get('serverInfo', {}).get('version')}")
        tools = [tool.get("name") for tool in door.send("tools/list").get("result", {}).get("tools", [])]
        if "status" not in tools:
            report.add("failed", "tools", f"{check}: tools/list has no status: {tools}")
            return None
        if not quiet:
            report.add("passed", "tools", "tools/list: " + ", ".join(sorted(tools)))
        deadline = time.monotonic() + CALL_SECONDS
        while True:
            answer = door.send("tools/call", {"name": "status", "arguments": {}}).get("result", {})
            text = _text(answer)
            if not text.startswith("starting") or time.monotonic() > deadline:
                break
            time.sleep(1)
        outcome, detail = root_verdict(text or json.dumps(answer), project)
        report.add(outcome, check, detail)
        found = ROOT_IN.search(text.splitlines()[0] if text else "")
        return found["root"] if found else None
    except (TimeoutError, OSError, ValueError) as error:
        report.add("failed", "handshake", f"{check}: {error}")
        return None
    finally:
        door.close()


def check_cli(cli: str | None, plugin: Path, project: Path, env: dict[str, str], report: Report) -> None:
    """What a Copilot CLI reads of the plugin without signing in: the plugin, its skills from the
    Copilot layout, and its MCP server."""
    if cli is None:
        report.add("skipped", "copilot-cli", "no Copilot CLI on PATH (or --cli); "
                   "`npm install -g @github/copilot` adds one")
        return
    env = {**env, "COPILOT_AUTO_UPDATE": "false"}

    def read(*arguments: str):
        done = subprocess.run([cli, f"--plugin-dir={plugin}", *arguments, "--json"], cwd=project, env=env,
                              capture_output=True, text=True, check=False, timeout=120)
        return json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else done

    plugins = read("plugin", "list")
    if isinstance(plugins, subprocess.CompletedProcess):
        report.add("failed", "copilot-cli", f"`plugin list` exit {plugins.returncode}: {plugins.stderr.strip()[:200]}")
        return
    versions = [str(item.get("version")) for item in plugins if isinstance(item, dict)
                and item.get("name") == se_plugin.PLUGIN] if isinstance(plugins, list) else []
    skills = read("skill", "list")
    paths = {item.get("name"): item.get("path", "") for item in skills if isinstance(item, dict)} \
        if isinstance(skills, list) else {}
    layout = [name for name in SKILLS if PurePosixPath(Path(paths.get(name, "")).as_posix()).parent
              == PurePosixPath((plugin / ".github" / "skills").as_posix())]
    server = read("mcp", "get", se_plugin.MCP_SERVER)
    server = server.get(se_plugin.MCP_SERVER, {}) if isinstance(server, dict) else {}
    if not versions or len(layout) != len(SKILLS) or not server:
        report.add("failed", "copilot-cli", f"plugin versions {versions}, skills from .github/skills "
                   f"{layout}, server {bool(server)}")
        return
    report.add("passed", "copilot-cli", f"plugin {se_plugin.PLUGIN} {versions[0]}; skills "
               f"{', '.join(layout)} from .github/skills; server {se_plugin.MCP_SERVER}: "
               f"{server.get('command')} {' '.join(server.get('args', []))}, cwd {server.get('cwd', '(none)')}")
    if server.get("cwd") == se_plugin.COPILOT_PLUGIN_ROOT and "." in server.get("args", []):
        report.add("noted", "mcp-root", f"the CLI starts a plugin's server in {se_plugin.COPILOT_PLUGIN_ROOT}, "
                   "so `--root .` names the plugin folder and the launcher picks the project (the "
                   "status lines above): a signed-in Copilot run confirms it (docs/copilot.md, "
                   "\"Monday checklist\")")


def _binary(build: bool, workdir: Path) -> tuple[Path | None, str]:
    """The `se` binary the door runs: SE's start's release in ~/.se/bin, or with `build` (or without
    that release) one built from this tree's components."""
    version = tomllib.loads((ROOT / "components" / "release.toml").read_text(encoding="utf-8"))["version"]
    suffix = ".exe" if os.name == "nt" else ""
    release = Path.home() / ".se" / "bin" / f"se-{version}{suffix}"
    if not build and release.is_file():
        return release, f"release se {version} in ~/.se/bin"
    if shutil.which("go") is None:
        return None, f"neither se {version} in ~/.se/bin nor Go to build it; run SE's start (bootstrap.sh)"
    target = workdir / f"se{suffix}"
    done = subprocess.run(["go", "build", "-o", str(target), "./cmd/se"], cwd=ROOT / "components",
                          capture_output=True, text=True, check=False)
    if done.returncode:
        return None, f"go build ./cmd/se failed: {done.stderr.strip()[-300:]}"
    return target, "se built from this tree's components"


def self_test(build: bool = False, cli: str | None = None, keep: bool = False) -> int:
    report = Report([])
    work = Path(tempfile.mkdtemp(prefix="se-copilot-self-test-"))
    plugin, project, home = work / "plugin" / "se", work / "project", work / "home"
    binary, roots = None, []
    base = clean_env(dict(os.environ))
    try:
        shutil.copytree(ROOT, plugin, ignore=NOT_COPIED)
        project.mkdir()
        home.mkdir()
        initialised = git_door.run("init", "-q", root=project)
        if initialised.returncode or (project / "se.toml").exists():
            report.add("failed", "project", f"git init in {project}: {initialised.stderr.strip()}")
            return 1
        report.add("passed", "project", f"SE copied to {plugin}, an empty git project at {project}, not SE")
        check_layout(plugin, report)
        check_hooks(plugin, report)
        binary, source = _binary(build, work)
        if binary is None:
            report.add("failed", "binary", source)
        else:
            report.add("passed", "binary", source)
            roots = check_door(plugin, project, {**base, "SE_MCP_BIN": str(binary)}, report)
        check_cli(cli or shutil.which("copilot"), plugin, project,
                  {**base, "HOME": str(home), "USERPROFILE": str(home)}, report)
    finally:
        if binary is not None:
            for root in dict.fromkeys([str(project), *roots]):
                subprocess.run([str(binary), "stop", "--root", root], capture_output=True, check=False,
                               timeout=60)
        if keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    failed = report.count("failed")
    print(f"copilot self-test: {report.count('passed')} passed, {failed} failed, "
          f"{report.count('skipped')} skipped, {report.count('noted')} noted{'' if keep else '; cleaned up'}")
    return 1 if failed else 0


# --- smoke verdict --------------------------------------------------------------------------------

GREETING = re.compile(r"SE \d+\.\d+\.\d+ started:")
# The names a host gives a tool of the server `se`: Copilot CLI's `se-<tool>`, VS Code's `se/<tool>`,
# Claude Code's `mcp__se__<tool>`.
SE_TOOL = re.compile(r"^(?:se[-/]|mcp__se__)(?P<tool>[a-z][a-z0-9-]*)$")
NAME_KEYS = ("toolName", "tool_name", "name", "tool")


def _objects(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _se_tool(item: dict) -> str | None:
    for key in NAME_KEYS:
        name = item.get(key)
        if isinstance(name, str):
            match = SE_TOOL.match(name)
            if match:
                return match["tool"]
            if item.get("mcpServerName") == se_plugin.MCP_SERVER or item.get("serverName") == se_plugin.MCP_SERVER:
                return name
    return None


def _failed(item: dict) -> bool:
    return item.get("success") is False or item.get("isError") is True or bool(item.get("error"))


def smoke_verdict(lines: list[str], exit_code: int = 0) -> tuple[bool, str]:
    """Passed where the JSON lines hold SE's greeting and an `se` tool call none of whose events
    failed, and Copilot exited 0."""
    events = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            return False, f"line {number} is no JSON: {line.strip()[:120]}"
    results = [event for event in events if isinstance(event, dict) and event.get("type") == "result"]
    code = exit_code or next((event.get("exitCode") for event in results if event.get("exitCode")), 0)
    greeting = next((match.group(0) for text in _strings(events) for match in [GREETING.search(text)] if match),
                    None)
    calls = [(tool, item) for item in _objects(events) for tool in [_se_tool(item)] if tool]
    failed = sorted({tool for tool, item in calls if _failed(item)})
    problems = []
    if code:
        problems.append(f"copilot exited {code}")
    if greeting is None:
        problems.append("no greeting `SE <version> started:`")
    if not calls:
        problems.append("no call of an se tool")
    if failed:
        problems.append("se tool call failed: " + ", ".join(failed))
    if problems:
        return False, "; ".join(problems)
    tools = sorted({tool for tool, _ in calls})
    return True, f"greeting `{greeting}` and se tool {', '.join(tools)} answered"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="copilot.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install", help="install SE into another repository for Copilot")
    install_parser.add_argument("--repo", type=Path, required=True, help="the repository")
    install_parser.add_argument("--no-sync", action="store_true", help="pin SE but do not clone it yet")
    test = commands.add_parser("self-test", help="install SE beside an empty project and check it without Copilot")
    test.add_argument("--build", action="store_true", help="build the door's binary from this tree "
                      "instead of using SE's start's release in ~/.se/bin")
    test.add_argument("--cli", help="the Copilot CLI to read the plugin with (default: `copilot` on PATH)")
    test.add_argument("--keep", action="store_true", help="keep the temporary folder and name it")
    verdict = commands.add_parser("smoke-verdict", help="judge the JSON lines of a Copilot smoke run")
    verdict.add_argument("lines", type=Path, help="the file copilot's --output-format json wrote")
    verdict.add_argument("--exit-code", type=int, default=0, help="copilot's own exit code")
    args = parser.parse_args(argv)
    if args.command == "install":
        return install(args.repo, None if args.no_sync else sync)
    if args.command == "self-test":
        return self_test(args.build, args.cli, args.keep)
    passed, detail = smoke_verdict(args.lines.read_text(encoding="utf-8").splitlines(), args.exit_code)
    print(f"copilot smoke: {'passed' if passed else 'failed'}: {detail}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
