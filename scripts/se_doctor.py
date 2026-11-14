"""SE's doctor: one read-only report of the box SE runs in, to paste whole when something half-works.

    uv run python <se>/scripts/se_doctor.py [--root <dir>] [--json] [--strict] [--offline]

It measures the host, the SE checkout against its upstream, the installed plugin and the `se`
binary against the pins, the core (standing file, pid, boot id, the last lines of its log), each
hook and MCP server registration a host reads, `gh` and the reach of the hosts SE fetches from.
Each line is "seen", "silent" (asked, no answer) or "not measured"; the most important finding
comes first. README "Doctor" owns what it reports.

Three layers, so the form can change without the checks:

- `gather` reads the facts into one plain dict (JSON data, nothing else): files, `git` through its
  door, `kern status`, `gh auth status` and a HEAD request per host, each with a short timeout.
- `diagnose` is pure: facts in, findings out; the tests hand it fake facts.
- `render_text` and `render_json` format the findings.

It writes nothing, starts nothing that stays, and prints no secret: never a token, a bus user, an
environment value, an e-mail address or a private path (home is `~`, the checkout `<checkout>`, any
other path only its last part). It exits 0, or with `--strict` 1 where a finding is a problem.

What it reuses rather than computes again: se_start's plugin registry and skills folder
(`plugin_registry`, `_claude_dir`), its cached release check (`Cache`, `default_cache`), its
`kern_status` and cloud marker (`CLOUD_ENV`); se_modules' binary pin (`app_binary`, `app_root`).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path


def _load(name: str):
    """A sibling script, loaded once under its own name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


git_door = _load("git_door")
se_modules = _load("se_modules")
se_start = _load("se_start")

SE_ROOT = Path(__file__).resolve().parents[1]
SEEN, SILENT, NOT_MEASURED = "seen", "silent", "not measured"
PROBLEM, NOTE, OK = "problem", "note", "ok"
# The hosts SE fetches from: GitHub (clones, releases, the API), uv's installer, Python and Go
# packages.
HOSTS = ("github.com", "api.github.com", "objects.githubusercontent.com", "astral.sh", "pypi.org",
         "proxy.golang.org")
NET_TIMEOUT = 3.0  # seconds a reachability check may take
GH_TIMEOUT = 5.0
LOG_LINES = 3
# Most important first: a stale program explains most of what half-works.
AREAS = ("binary", "plugin", "core", "hooks", "checkout", "gh", "network", "host")
SCRIPT_SUFFIXES = (".sh", ".py", ".ps1", ".js", ".mjs", ".cjs", ".ts")


@dataclass(frozen=True)
class Finding:
    area: str
    state: str  # SEEN, SILENT, NOT_MEASURED
    level: str  # PROBLEM, NOTE, OK
    text: str


# Redaction


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PROFILE = re.compile(r"(/home/|/Users/|[A-Za-z]:\\Users\\)[^/\\\s]+")
USERINFO = re.compile(r"(\w+://)[^/@\s]+@")


def shown(path: Path | str, checkout: Path, home: Path) -> str:
    """A path as the report may print it: `<checkout>/…`, `~/…`, else only its last part."""
    path = Path(path)
    for base, name in ((checkout, "<checkout>"), (home, "~")):
        try:
            rest = path.relative_to(base).as_posix()
        except ValueError:
            continue
        return name if rest == "." else f"{name}/{rest}"
    return f".../{path.name}"


def redact(text: str, checkout: Path, home: Path) -> str:
    """A line of someone else's output as the report may print it."""
    for base, name in ((str(checkout), "<checkout>"), (str(home), "~")):
        if len(base) > 1:
            text = text.replace(base, name)
    text = USERINFO.sub(r"\1", text)
    return PROFILE.sub(r"\1<name>", EMAIL.sub("<e-mail>", text))


# Gathering: the only part that reads the box


def _version_of(path: Path, name: str) -> str | None:
    """The version a fetched binary's file name carries: `<name>-<version>[.exe]`."""
    match = re.fullmatch(rf"{re.escape(name)}-(\d+\.\d+\.\d+)(\.exe)?", path.name)
    return match.group(1) if match else None


def _json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def gather_host(env: dict[str, str]) -> dict:
    """Which host runs this, from the names of its variables (only one value is read: the cloud
    marker). Small on purpose: a host table SE keeps elsewhere replaces it."""
    names = set(env)
    if "CLAUDECODE" in names or "CLAUDE_CODE_ENTRYPOINT" in names:
        return {"name": "claude-code", "cloud": env.get(se_start.CLOUD_ENV) == "true"}
    if any(n.startswith(("COPILOT_", "GITHUB_COPILOT")) for n in names):
        return {"name": "copilot", "cloud": env.get("GITHUB_ACTIONS") == "true"}
    return {"name": "other", "cloud": env.get("GITHUB_ACTIONS") == "true"}


def _git(root: Path, *args: str) -> str | None:
    result = git_door.run(*args, root=root, timeout=10)
    return result.stdout.strip() if result.returncode == 0 else None


def gather_checkout(checkout: Path, git=_git) -> dict:
    """The checkout's commit against its upstream as last fetched; it fetches nothing."""
    if not (checkout / ".git").exists():
        return {"git": False, "version": _version(checkout)}
    head = git(checkout, "rev-parse", "--short", "HEAD")
    upstream = git(checkout, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream is None:
        default = git(checkout, "rev-parse", "--abbrev-ref", "origin/HEAD")
        upstream = default if default and default != "origin/HEAD" else (
            "origin/main" if git(checkout, "rev-parse", "--verify", "--quiet", "origin/main") else None)
    ahead = behind = None
    if upstream:
        counts = git(checkout, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
        if counts and len(counts.split()) == 2:
            ahead, behind = (int(n) for n in counts.split())
    return {"git": True, "head": head, "upstream": upstream, "ahead": ahead, "behind": behind,
            "version": _version(checkout)}


def _version(root: Path) -> str | None:
    version = _toml(root / se_modules.MANIFEST).get("project", {}).get("version")
    return version if isinstance(version, str) else None


def _plugin_roots(claude_dir: Path, registry: Path) -> list[Path]:
    """Every installed SE plugin: Claude Code's record of the installed plugins and a plugin cloned
    into its skills folder (as the cloud's SE is)."""
    roots: list[Path] = []
    plugins = (_json(registry) or {}).get("plugins", {})
    for name, entries in (plugins.items() if isinstance(plugins, dict) else []):
        if name.partition("@")[0] != "se":
            continue
        for entry in entries if isinstance(entries, list) else [entries]:
            if isinstance(entry, dict) and isinstance(entry.get("installPath"), str):
                roots.append(Path(entry["installPath"]))
    for manifest in sorted((claude_dir / "skills").glob(f"*/{se_start.PLUGIN_MANIFEST}")):
        if (_json(manifest) or {}).get("name") == "se":
            roots.append(manifest.parent.parent)
    return list(dict.fromkeys(roots))


def gather_plugins(roots: list[Path], checkout: Path, home: Path) -> list[dict]:
    return [{"where": shown(root, checkout, home),
             "version": (_json(root / se_start.PLUGIN_MANIFEST) or {}).get("version"),
             "exists": root.is_dir()} for root in roots]


def gather_latest(cache_path: Path, now: float) -> dict | None:
    """SE's latest release as the start's last update check cached it."""
    cache = se_start.Cache.read(cache_path)
    if cache.checked_at is None:
        return None
    entry = cache.remotes.get("https://github.com/mb-89/SE") or next(iter(cache.remotes.values()), {})
    versions = [tuple(v) for v in entry.get("versions", []) if isinstance(v, list) and len(v) == 3]
    if not versions:
        return None
    return {"version": ".".join(map(str, max(versions))), "age_seconds": int(now - cache.checked_at)}


def gather_binary(app_root: Path, project: Path, home: Path, checkout: Path) -> dict:
    try:
        pin = se_modules.app_binary(app_root)
    except se_modules.ModuleError as error:
        return {"pinned": None, "error": redact(str(error), checkout, home), "copies": []}
    copies = []
    found = shutil.which(pin.name)
    places = [("PATH", Path(found) if found else None),
              ("~/.se/bin", home / ".se" / "bin" / pin.name)]
    try:
        started = (project / ".se" / ".runtime" / "kern.path").read_text(encoding="utf-8").strip()
        places.append(("the core's start", Path(started) if started else None))
    except OSError:
        places.append(("the core's start", None))
    for where, path in places:
        if path is None or not path.exists():
            copies.append({"where": where, "exists": False, "version": None})
            continue
        copies.append({"where": where, "exists": True, "version": _version_of(path.resolve(), pin.name),
                       "file": shown(path.resolve(), checkout, home)})
    return {"name": pin.name, "pinned": pin.version, "copies": copies}


def _pid_alive(pid: int) -> bool | None:
    """Whether the process runs, where the box shows it without signalling it (Linux's /proc)."""
    proc = Path("/proc")
    return (proc / str(pid)).is_dir() if proc.is_dir() else None


def gather_core(project: Path, binary: Path | None, home: Path, checkout: Path,
                status=se_start.kern_status) -> dict:
    runtime = project / ".se" / ".runtime"
    standing = _json(runtime / "standing.json")
    answer = status(binary, project) if binary and binary.exists() else None
    core: dict = {"standing": standing is not None, "asked": bool(binary and binary.exists())}
    if standing is not None:
        pid = standing.get("pid")
        core |= {"pid": pid if isinstance(pid, int) else None, "boot": standing.get("boot"),
                 "started": standing.get("started")}  # never its users: they are the bus's secrets
    state = (answer or {}).get("state")
    core["status"] = state if isinstance(state, str) else None
    health_pid = ((answer or {}).get("health") or {}).get("pid")
    if state == "running" and health_pid == core.get("pid"):
        core["alive"] = True
    elif core.get("pid"):
        core["alive"] = _pid_alive(core["pid"])
    try:
        lines = (runtime / "core.log").read_text(encoding="utf-8", errors="replace").splitlines()
        core["log"] = [redact(line, checkout, home)[:160] for line in lines[-LOG_LINES:]]
    except OSError:
        core["log"] = None
    return core


def _commands(node) -> list[str]:
    """Every command string in a hooks tree, in Claude Code's or Copilot's shape."""
    found: list[str] = []
    if isinstance(node, dict):
        for key in ("command", "bash", "powershell"):
            if isinstance(node.get(key), str):
                found.append(node[key])
        for value in node.values():
            if isinstance(value, (dict, list)):
                found += _commands(value)
    elif isinstance(node, list):
        for item in node:
            found += _commands(item)
    return found


def _scripts(command: str, variables: dict[str, Path], project: Path) -> list[tuple[str, Path | None]]:
    """The scripts a command names, each with its path where it resolves (None: it names a variable
    the doctor cannot fill)."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    found = []
    for word in words:
        if not word.lower().endswith(SCRIPT_SUFFIXES):
            continue
        text = word
        for name, value in variables.items():
            text = text.replace(f"${{{name}}}", str(value)).replace(f"${name}", str(value))
        if text.startswith("~"):
            text = str(variables["HOME"]) + text[1:]
        if "$" in text or "%" in text:
            found.append((word, None))
            continue
        path = Path(text)
        found.append((word, path if path.is_absolute() else project / path))
    return found


def _registration(file: Path, kind: str, entries: dict[str, list[str]], variables: dict[str, Path],
                  project: Path, checkout: Path, home: Path) -> dict:
    items = []
    for name, commands in entries.items():
        for command in commands:
            scripts = [{"script": shown(path, checkout, home) if path else word,
                        "exists": path.is_file() if path else None}
                       for word, path in _scripts(command, variables, project)]
            items.append({"name": name, "scripts": scripts})
    return {"file": shown(file, checkout, home), "kind": kind, "items": items}


def _hook_entries(data: dict) -> dict[str, list[str]]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return {}
    return {event: _commands(value) for event, value in hooks.items()}


def _mcp_entries(data: dict) -> dict[str, list[str]]:
    servers = data.get("mcpServers") or data.get("servers")
    if not isinstance(servers, dict):
        return {}
    entries = {}
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        words = [spec.get("command")] + list(spec.get("args") or [])
        entries[name] = [shlex.join(w for w in words if isinstance(w, str))] if spec.get("command") else []
    return entries


def gather_registrations(plugins: list[Path], project: Path, home: Path, claude_dir: Path,
                         checkout: Path) -> list[dict]:
    """Each file a host reads hooks or MCP servers from, and the scripts its entries name."""
    base = {"HOME": home, "CLAUDE_PROJECT_DIR": project}
    files: list[tuple[Path, str, Path | None]] = []  # file, kind, plugin root
    for root in plugins:
        files += [(root / se_start.PLUGIN_MANIFEST, "hooks", root), (root / "hooks" / "hooks.json", "hooks", root),
                  (root / se_start.PLUGIN_MANIFEST, "mcp", root), (root / ".mcp.json", "mcp", root)]
    for settings in (project / ".claude" / "settings.json", project / ".claude" / "settings.local.json",
                     claude_dir / "settings.json"):
        files.append((settings, "hooks", None))
    files += [(path, "hooks", None) for path in sorted((project / ".github" / "hooks").glob("*.json"))]
    files += [(project / ".mcp.json", "mcp", None), (home / ".claude.json", "mcp", None),
              (project / ".vscode" / "mcp.json", "mcp", None), (home / ".copilot" / "mcp-config.json", "mcp", None)]
    found = []
    for file, kind, root in files:
        data = _json(file) if file.is_file() else None
        if data is None:
            continue
        entries = _hook_entries(data) if kind == "hooks" else _mcp_entries(data)
        if not entries:
            continue
        variables = base | ({"CLAUDE_PLUGIN_ROOT": root} if root else {})
        found.append(_registration(file, kind, entries, variables, project, checkout, home))
    return found


def gather_gh() -> dict:
    """Whether gh is signed in; its output names the account, so only its exit code is kept."""
    if shutil.which("gh") is None:
        return {"installed": False, "signed_in": None}
    try:
        result = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=GH_TIMEOUT,
                                stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return {"installed": True, "signed_in": None}
    return {"installed": True, "signed_in": result.returncode == 0}


def _reach(host: str) -> bool:
    request = urllib.request.Request(f"https://{host}/", method="HEAD",
                                     headers={"User-Agent": "se-doctor"})
    try:
        urllib.request.urlopen(request, timeout=NET_TIMEOUT).close()
    except urllib.error.HTTPError:
        return True  # the host answered, with whatever status
    except (OSError, ValueError):
        return False
    return True


def gather_network(hosts=HOSTS, reach=_reach) -> list[dict]:
    with ThreadPoolExecutor(max_workers=len(hosts)) as pool:
        return [{"host": h, "reached": r} for h, r in zip(hosts, pool.map(reach, hosts))]


def checkout_of(se_root: Path, project: Path) -> Path:
    """The SE checkout measured: the project where it is SE's own checkout, else the SE that runs."""
    return se_modules.app_root(se_root, project) if (project / se_modules.MANIFEST).is_file() else se_root


def gather(se_root: Path, project: Path, offline: bool = False, env: dict[str, str] | None = None,
           home: Path | None = None) -> dict:
    """Every fact the doctor reports, as plain data."""
    env = dict(os.environ if env is None else env)
    home = home or Path.home()
    claude_dir = Path(env.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    checkout = checkout_of(se_root, project).resolve()
    roots = _plugin_roots(claude_dir, claude_dir / "plugins" / "installed_plugins.json")
    binary = gather_binary(checkout, project, home, checkout)
    started = project / ".se" / ".runtime" / "kern.path"
    try:
        core_binary = Path(started.read_text(encoding="utf-8").strip())
    except OSError:
        core_binary = home / ".se" / "bin" / str(binary.get("name") or "se")
    return {
        "host": gather_host(env),
        "checkout": gather_checkout(checkout),
        "plugins": gather_plugins(roots, checkout, home),
        "latest": gather_latest(se_start.default_cache(), time.time()),
        "binary": binary,
        "core": gather_core(project, core_binary, home, checkout),
        "registrations": gather_registrations(roots, project, home, claude_dir, checkout),
        "gh": None if offline else gather_gh(),
        "network": None if offline else gather_network(),
    }


# Diagnosis: pure, facts in, findings out


def _key(version: str | None) -> tuple[int, ...] | None:
    parsed = se_modules.parse_version(version)
    return tuple(parsed) if parsed else None


def check_host(host: dict | None) -> list[Finding]:
    if not host:
        return [Finding("host", NOT_MEASURED, NOTE, "host not measured")]
    where = "a cloud session" if host.get("cloud") else "a local session"
    return [Finding("host", SEEN, OK, f"{host.get('name')}, {where}")]


def check_checkout(checkout: dict | None) -> list[Finding]:
    if not checkout:
        return [Finding("checkout", NOT_MEASURED, NOTE, "SE checkout not measured")]
    version = checkout.get("version") or "?"
    if not checkout.get("git"):
        return [Finding("checkout", SEEN, OK, f"SE {version}, an installed copy (no git)")]
    upstream, ahead, behind = checkout.get("upstream"), checkout.get("ahead"), checkout.get("behind")
    head = f"SE {version} at {checkout.get('head') or '?'}"
    if not upstream or behind is None:
        return [Finding("checkout", SILENT, NOTE, f"{head}; no upstream to compare with")]
    text = f"{head}; {ahead} ahead, {behind} behind {upstream} as last fetched"
    return [Finding("checkout", SEEN, PROBLEM if behind else OK, text)]


def check_plugins(plugins: list[dict] | None, checkout: dict | None, latest: dict | None) -> list[Finding]:
    if plugins is None:
        return [Finding("plugin", NOT_MEASURED, NOTE, "plugins not measured")]
    if not plugins:
        return [Finding("plugin", SILENT, NOTE, "no installed SE plugin found")]
    findings = []
    here = (checkout or {}).get("version")
    newest = (latest or {}).get("version")
    for plugin in plugins:
        version, where = plugin.get("version"), plugin.get("where")
        if not plugin.get("exists") or version is None:
            findings.append(Finding("plugin", SILENT, PROBLEM, f"SE plugin at {where} names no version"))
            continue
        behind = [f"the checkout's {here}" for ref in [here] if _key(ref) and _key(version) < _key(ref)]
        behind += [f"the latest release {newest} (checked {latest['age_seconds'] // 60} min ago)"
                   for ref in [newest] if _key(ref) and _key(version) < _key(ref)]
        if behind:
            findings.append(Finding("plugin", SEEN, PROBLEM,
                                    f"stale plugin: SE {version} at {where} is behind " + " and ".join(behind)))
        else:
            findings.append(Finding("plugin", SEEN, OK, f"SE {version} at {where}, current"))
    return findings


def check_binary(binary: dict | None) -> list[Finding]:
    if not binary:
        return [Finding("binary", NOT_MEASURED, NOTE, "binary not measured")]
    if binary.get("pinned") is None:
        return [Finding("binary", NOT_MEASURED, PROBLEM, f"no pin readable: {binary.get('error')}")]
    name, pinned = binary["name"], binary["pinned"]
    findings = []
    for copy in binary.get("copies", []):
        where = copy["where"]
        if not copy.get("exists"):
            findings.append(Finding("binary", SILENT, NOTE, f"{name} not found on {where}"))
        elif copy.get("version") is None:
            findings.append(Finding("binary", SEEN, NOTE,
                                    f"{name} on {where} ({copy.get('file')}) carries no version; pin {pinned}"))
        elif copy["version"] != pinned:
            findings.append(Finding("binary", SEEN, PROBLEM,
                                    f"stale binary: {name} {copy['version']} on {where}; the pin is {pinned}"))
        else:
            findings.append(Finding("binary", SEEN, OK, f"{name} {pinned} on {where}, the pin"))
    return findings


def check_core(core: dict | None) -> list[Finding]:
    if not core:
        return [Finding("core", NOT_MEASURED, NOTE, "core not measured")]
    findings = []
    if not core.get("standing"):
        state = SILENT if core.get("asked") else NOT_MEASURED
        level = PROBLEM if core.get("status") == "running" else NOTE
        findings.append(Finding("core", state, level, f"no standing file; status {core.get('status') or 'silent'}"))
    else:
        pid, boot, alive, status = core.get("pid"), core.get("boot") or "?", core.get("alive"), core.get("status")
        record = f"pid {pid}, boot {boot}"
        if alive is False:
            findings.append(Finding("core", SEEN, PROBLEM,
                                    f"dead core record: the standing file names {record}, which is not running"))
        elif status == "running":
            findings.append(Finding("core", SEEN, OK, f"running, {record}"))
        elif alive and status is None:
            findings.append(Finding("core", SILENT, PROBLEM, f"{record} runs but its status does not answer"))
        else:
            state = SEEN if status else (SILENT if core.get("asked") else NOT_MEASURED)
            findings.append(Finding("core", state, NOTE, f"{record}; status {status or 'silent'}; pid alive "
                                    f"{'not measured' if alive is None else alive}"))
    log = core.get("log")
    if log is None:
        findings.append(Finding("core", SILENT, NOTE, "no core.log"))
    else:
        findings.append(Finding("core", SEEN, OK, "core.log ends:" + "".join(f"\n    {line}" for line in log)))
    return findings


def check_registrations(registrations: list[dict] | None) -> list[Finding]:
    if registrations is None:
        return [Finding("hooks", NOT_MEASURED, NOTE, "registrations not measured")]
    if not registrations:
        return [Finding("hooks", SILENT, NOTE, "no hook or MCP server registration found")]
    findings = []
    for reg in registrations:
        missing, unresolved, count = [], [], 0
        for item in reg.get("items", []):
            for script in item.get("scripts", []):
                count += 1
                if script.get("exists") is False:
                    missing.append(f"{item['name']} names {script['script']}")
                elif script.get("exists") is None:
                    unresolved.append(script["script"])
        label = f"{reg['file']} ({reg['kind']}, {len(reg.get('items', []))} entries)"
        for text in missing:
            findings.append(Finding("hooks", SEEN, PROBLEM, f"missing hook script: {label}: {text}, which does not exist"))
        if unresolved:
            findings.append(Finding("hooks", NOT_MEASURED, NOTE, f"{label}: cannot resolve {', '.join(sorted(set(unresolved)))}"))
        if not missing and not unresolved:
            findings.append(Finding("hooks", SEEN, OK, f"{label}: {count} scripts named, all exist"))
    return findings


def check_gh(gh: dict | None) -> list[Finding]:
    if gh is None:
        return [Finding("gh", NOT_MEASURED, NOTE, "gh not measured (offline)")]
    if not gh.get("installed"):
        return [Finding("gh", SILENT, NOTE, "gh is not installed")]
    if gh.get("signed_in") is None:
        return [Finding("gh", SILENT, NOTE, "gh auth status did not answer")]
    return [Finding("gh", SEEN, OK if gh["signed_in"] else NOTE,
                    "gh signed in" if gh["signed_in"] else "gh not signed in")]


def check_network(network: list[dict] | None) -> list[Finding]:
    if network is None:
        return [Finding("network", NOT_MEASURED, NOTE, "network not measured (offline)")]
    silent = [n["host"] for n in network if not n.get("reached")]
    reached = [n["host"] for n in network if n.get("reached")]
    findings = []
    if silent:
        findings.append(Finding("network", SILENT, PROBLEM, f"no answer from {', '.join(silent)}"))
    if reached:
        findings.append(Finding("network", SEEN, OK, f"reached {', '.join(reached)}"))
    return findings


def diagnose(facts: dict) -> list[Finding]:
    """Every finding, the most important first: problems, then notes, then what is fine; within a
    level by AREAS."""
    findings = (check_host(facts.get("host")) + check_checkout(facts.get("checkout"))
                + check_plugins(facts.get("plugins"), facts.get("checkout"), facts.get("latest"))
                + check_binary(facts.get("binary")) + check_core(facts.get("core"))
                + check_registrations(facts.get("registrations")) + check_gh(facts.get("gh"))
                + check_network(facts.get("network")))
    rank = {PROBLEM: 0, NOTE: 1, OK: 2}
    return sorted(findings, key=lambda f: (rank[f.level], AREAS.index(f.area)))


# Output


REUSED = ("reused: se_start (plugin registry, cached release check, kern status, cloud marker), "
          "se_modules (binary pin)")


def render_text(findings: list[Finding]) -> str:
    problems = sum(f.level == PROBLEM for f in findings)
    notes = sum(f.level == NOTE for f in findings)
    lines = [f"SE doctor: {problems} problem{'s' * (problems != 1)}, {notes} note{'s' * (notes != 1)} "
             "(read-only; nothing was changed)"]
    marks = {PROBLEM: "!", NOTE: "-", OK: " "}
    for f in findings:
        lines.append(f"{marks[f.level]} {f.area:<8} [{f.state}] {f.text}")
    lines.append(REUSED)
    return "\n".join(lines) + "\n"


def render_json(findings: list[Finding], facts: dict) -> str:
    return json.dumps({"findings": [asdict(f) for f in findings], "facts": facts, "reused": REUSED},
                      indent=1) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="se_doctor.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=None, help="the project (default: the working directory)")
    parser.add_argument("--json", action="store_true", help="the same report as data")
    parser.add_argument("--strict", action="store_true", help="exit 1 where a finding is a problem")
    parser.add_argument("--offline", action="store_true", help="skip gh and the network reach")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project = (args.root or Path.cwd()).resolve()
    facts = gather(SE_ROOT, project, offline=args.offline)
    findings = diagnose(facts)
    sys.stdout.write(render_json(findings, facts) if args.json else render_text(findings))
    return 1 if args.strict and any(f.level == PROBLEM for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
