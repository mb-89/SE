"""kern, the Go core, as SE uses it from kern's repository at the pin se.toml [components.kern] reads
from components/go.mod: the check main requires, the release of `se` on it, the battery every
application calls, and kern's application template in the pinned clone."""

import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

import ci_trust  # scripts/ is on the path (tests/conftest.py)
import fake_processes
import se_modules

PROJECT = Path(__file__).resolve().parents[1]


WORKFLOW = PROJECT / ".github" / "workflows" / "check.yml"
# The first major of actions/setup-go that runs on Node 24.
SETUP_GO_NODE_24 = 6


def test_the_required_check_vets_ses_go_components_on_kern_at_the_pin_their_go_mod_requires() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    jobs = workflow[workflow.index("\njobs:\n"):]
    assert re.findall(r"(?m)^  (\w[\w-]*):\n", jobs) == ["check", "kern-platforms", "kern-platforms-queue",
                                                         "trust"], (
        "the Go components run in the required job check, SE's start and hook on Windows in "
        "kern-platforms, which check needs and kern-platforms-queue bounds the queue of; trust "
        "decides whether either runs (README \"Trusted landings\")"
    )
    setups = re.findall(r"uses: actions/setup-go@v(\d+)\n        with:\n((?:          .*\n)+)", workflow)
    assert len(setups) == 1, "Go is set up on Linux only, for SE's Go components"
    [(major, inputs)] = setups
    assert int(major) >= SETUP_GO_NODE_24, "setup-go below v6 runs on Node 20"
    assert "go-version-file: components/go.mod" in inputs and "cache-dependency-path: components/go.sum" in inputs
    # kern is placed at its pin and the lock held to the require before anything reads kern (the
    # command reference imports its SDK), Go is set up before the vet, and the suite step runs the
    # components' tests as se.toml declares them.
    check = re.search(r"(?ms)^  check:\n(.*?)(?=^  \w|\Z)", jobs)[1]
    steps = ["uv run python scripts/se_modules.py sync kern", "git diff --exit-code -- se.lock",
             "scripts/work_tickets.py docs --check", "actions/setup-go", "time go vet ./...",
             "scripts/work_tickets.py suite --worktree .", "needs.kern-platforms.result"]
    assert [check.index(step) for step in steps] == sorted(check.index(step) for step in steps)
    assert "        working-directory: components\n        run: time go vet ./...\n" in check
    assert "working-directory: kern" not in workflow and "gofmt" not in workflow, "kern's own CI is kern's"
    assert "go test" not in check, "the components' tests have one declaration, se.toml [tests.beside.go-components]"


def lock_step() -> str:
    """The shell of the check job's step that places kern and holds se.lock to the require."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow[workflow.index("      - name: kern at the pin components/go.mod requires\n"):]
    lines = step.splitlines()
    lines = lines[lines.index("        run: |") + 1:]
    block = []
    for line in lines:
        if line.strip() and not line.startswith(" " * 10):
            break
        block.append(line[10:])
    return "\n".join(block)


def test_a_committed_lock_that_lags_the_require_fails_the_check_naming_the_sync() -> None:
    """The step runs before the components' vet, where trust is on too (it takes a second): it
    syncs kern and fails where se.lock then differs from what was committed."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    shell = lock_step()
    assert shell.splitlines()[:2] == ["uv run python scripts/se_modules.py sync kern",
                                      "if ! git diff --exit-code -- se.lock; then"]
    assert ("::error::se.lock does not lock the kern components/go.mod requires: run uv run python "
            "scripts/se_modules.py sync kern and commit se.lock") in shell
    assert "      - name: kern at the pin components/go.mod requires\n        run: |\n" in workflow
    replace = (PROJECT / "components" / "go.mod").read_text(encoding="utf-8")
    assert re.search(r"(?m)^replace kern => \.\./\.se/modules/kern$", replace)


def test_the_required_check_fails_unless_ses_start_and_hook_passed_on_windows() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    jobs = workflow[workflow.index("\njobs:\n"):]
    platforms = jobs[jobs.index("\n  kern-platforms:\n"):jobs.index("\n  kern-platforms-queue:\n")]
    check = re.search(r"(?ms)^  check:\n(.*?)(?=^  \w|\Z)", jobs)[1]
    assert "    runs-on: ${{ matrix.os }}\n" in platforms
    [matrix] = re.findall(r"(?m)^        os: \[(.*)\]$", platforms)
    assert matrix == "windows-2025", "the one leg is Windows; darwin is built by the release, not tested"
    assert "      fail-fast: false\n" in platforms, "each platform answers, whichever fails first"
    assert "go " not in platforms and "setup-go" not in platforms, "kern's Go tests on Windows are kern's"
    # SE's start and hook scripts, whose paths differ off Linux, run there in Git's bash.
    assert ("        shell: bash\n        run: uv run pytest -q tests/test_bootstrap.py tests/test_se_hook.py "
            "tests/test_se_mcp.py tests/test_runme.py\n") in platforms
    # RUNME.ps1 runs from PowerShell itself, Windows only; `-k powershell` selects its cases.
    assert ("      - name: RUNME from PowerShell\n        if: runner.os == 'Windows'\n        shell: powershell\n"
            "        run: uv run pytest -q tests/test_runme.py -k powershell\n") in platforms
    # The worktree clean-up's links (tests/test_worktree_removal.py), junctions among them, there too.
    assert "        shell: bash\n        run: uv run pytest -q -rs tests/test_worktree_removal.py\n" in platforms
    # setup.ps1 runs where PowerShell is, Windows only; `-k powershell` selects its SETUPS cases.
    assert ("        if: runner.os == 'Windows'\n        shell: bash\n"
            "        run: uv run pytest -q tests/test_public_check.py -k powershell\n") in platforms
    # The hand-off to Git's bash (scripts/bash.ps1) runs from PowerShell itself, Windows only.
    assert ("        if: runner.os == 'Windows'\n        shell: powershell\n"
            "        run: uv run pytest -q tests/test_windows_entry.py\n") in platforms
    assert "work_tickets.py suite" not in platforms, "the Python suite and its budget stay on Linux"
    assert "    needs: [trust, kern-platforms]\n" in check
    # A required check that is skipped counts as passed: check runs whatever kern-platforms answered.
    assert "    if: ${{ !cancelled() }}\n" in check
    assert re.search(r'if \[ "\$PLATFORMS" != success \]; then\n.*\n\s+exit 1', check), "check fails unless kern-platforms passed"
    assert "      - name: SE's start, hook and setup scripts passed on Windows\n" in check


RELEASE = PROJECT / ".github" / "workflows" / "kern-release.yml"
BATTERY = PROJECT / ".github" / "workflows" / "kern-battery.yml"
TEMPLATE = se_modules.kern_dir(PROJECT) / "template"  # kern at its pin (tests/conftest.py)
# The first major of each action kern's workflows use that runs on Node 24.
NODE_24 = {"actions/checkout": 5, "actions/setup-go": SETUP_GO_NODE_24, "actions/upload-artifact": 6,
           "actions/download-artifact": 7, "astral-sh/setup-uv": 7}

def workflow(path: Path) -> dict:
    """A workflow as GitHub reads it: YAML, its `on:` (YAML 1.1's true) under "on"."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in data:
        data["on"] = data.pop(True)
    return data


def step(job: dict, name: str) -> dict:
    """The one step of `job` named `name`, or whose `uses` is that action."""
    found = [s for s in job["steps"] if name in (s.get("name"), str(s.get("uses", "")).split("@")[0])]
    assert len(found) == 1, f"one step {name!r}, found {len(found)}"
    return found[0]


UNTRUSTED = "needs.trust.outputs.trusted != 'true'"
KERN_AT_THE_PIN = {"repository": "${{ job.workflow_repository }}", "ref": "${{ job.workflow_sha }}",
                   "path": ".kern-battery"}
INTEGRATOR_PASS = "./.kern-battery/.github/actions/integrator-pass"
# The one action that places kern, the battery's and the release's (README "Workflows").
KERN_AT_PIN = "./.github/actions/kern-at-pin"
ACTION = PROJECT / KERN_AT_PIN / "action.yml"


def test_the_battery_holds_the_applications_tests_to_se_toml_tests() -> None:
    battery = workflow(BATTERY)
    assert set(battery["on"]) == {"workflow_call"}
    assert battery["on"]["workflow_call"]["inputs"]["directory"]["default"] == "."
    job = battery["jobs"]["battery"]
    assert job["defaults"]["run"]["working-directory"] == "${{ inputs.directory }}"
    assert step(job, "actions/setup-go")["with"]["go-version-file"] == "${{ inputs.directory }}/go.mod"
    assert step(job, "The Go code vets")["run"] == "go vet ./..."
    tests = step(job, "The tests, within their budget")
    assert tests["shell"] == "python3 {0}"
    assert 'tests.get("command"), tests.get("target_seconds"), tests.get("limit_seconds")' in tests["run"]
    assert "if seconds > limit:" in tests["run"] and "if seconds > target:" in tests["run"]


def test_the_battery_passes_on_the_integrators_record_through_kern_at_the_applications_pin() -> None:
    """SE's README "Trusted landings": the job trust runs integrator-pass from the kern commit the
    battery runs at, the tag the application pins, and the battery's vet and tests run only where
    it does not vouch for the tree."""
    battery = workflow(BATTERY)
    assert list(battery["jobs"]) == ["trust", "battery"]
    # The caller's permissions apply: contents: read where trust is off, checks: write and
    # actions: read where an application turns it on.
    assert "permissions" not in battery
    assert all("permissions" not in job for job in battery["jobs"].values())
    trust = battery["jobs"]["trust"]
    assert trust["outputs"] == {"trusted": "${{ steps.lookup.outputs.trusted }}"}
    assert trust["steps"][0] == {"uses": "actions/checkout@v7", "with": {"fetch-depth": 0}}, (
        "the application's checkout, with the history full_every counts")
    kern = step(trust, "kern at the tag the application pins")
    assert kern["uses"] == "actions/checkout@v7" and KERN_AT_THE_PIN.items() <= kern["with"].items()
    sparse = kern["with"]["sparse-checkout"].split()
    lookup = step(trust, "The integrator's record of this tree")
    assert lookup["id"] == "lookup" and lookup["uses"] == INTEGRATOR_PASS
    assert lookup["with"] == {"mode": "lookup", "worktree": "${{ inputs.directory }}"}
    # What the sparse checkout holds is what the action runs: its action.yml and SE's scripts.
    action = PROJECT / INTEGRATOR_PASS.removeprefix("./.kern-battery/") / "action.yml"
    assert action.is_file()
    assert '"$GITHUB_ACTION_PATH/../../../scripts/ci_trust.py"' in action.read_text(encoding="utf-8")
    assert sparse == [".github/actions", "scripts"]
    assert (PROJECT / "scripts" / "ci_trust.py").is_file() and (PROJECT / "scripts" / "git_door.py").is_file()

    job = battery["jobs"]["battery"]
    assert job["needs"] == "trust"
    assert job["steps"][0] == {"uses": "actions/checkout@v7"}
    notice = step(job, "The integrator's record of this tree is trusted")
    assert notice["if"] == "needs.trust.outputs.trusted == 'true'"
    for name in ("kern at the pin", "actions/setup-go", "astral-sh/setup-uv", "The Go code vets",
                 "The tests, within their budget"):
        assert step(job, name)["if"] == UNTRUSTED, name
    # kern at the commit the application's se.lock locks, before the vet builds on it.
    kern = step(job, "kern at the pin")
    assert kern["uses"] == KERN_AT_PIN and kern["with"] == {"folder": "${{ inputs.directory }}"}
    order = [s.get("name") or s.get("uses") for s in job["steps"]]
    assert order.index("actions/checkout@v7") < order.index("kern at the pin") < order.index("The Go code vets")
    # The safety net's bookkeeping, after the tests: kern's action at the pin, a full pass marked, a
    # failure's trusted records named.
    names = [s.get("name") for s in job["steps"]]
    net = step(job, "kern at the tag the application pins, for the safety net")
    assert names.index(net["name"]) > names.index("The tests, within their budget")
    assert net["if"] == f"${{{{ !cancelled() && {UNTRUSTED} }}}}"
    assert KERN_AT_THE_PIN.items() <= net["with"].items() and net["with"]["sparse-checkout"].split() == sparse
    for name, mode, when in (("Mark the full pass", "full-pass", "success()"),
                             ("Name the trusted records the failure came through", "finding", "failure()")):
        bookkeeping = step(job, name)
        assert bookkeeping["uses"] == INTEGRATOR_PASS
        assert bookkeeping["with"] == {"mode": mode, "worktree": "${{ inputs.directory }}"}
        assert bookkeeping["if"] == f"{when} && {UNTRUSTED}", name
        assert names.index(name) > names.index(net["name"])
    assert set(ci_trust.COMMANDS) >= {"lookup", "full-pass", "finding"}


def test_the_template_is_a_bare_application_in_ses_shape() -> None:
    """docs/go-core.md "A bare application, and `se new app`"."""
    for path in ("go.mod", "cmd/app/main.go", "components/doc.go", "types/doc.go", "wiring.toml",
                 "se.toml", "AGENTS.md", "README.md", "tests/test_core.py", "tests/test_go.py",
                 ".github/workflows/check.yml"):
        assert (TEMPLATE / path).is_file(), path
    settings = tomllib.loads((TEMPLATE / "se.toml").read_text(encoding="utf-8"))
    assert settings["tests"]["command"] == ["uv", "run", "pytest", "-q"]
    assert 0 < settings["tests"]["target_seconds"] <= settings["tests"]["limit_seconds"]
    assert settings["modules"]["kern"]["go"] is True
    assert tomllib.loads((TEMPLATE / "wiring.toml").read_text(encoding="utf-8")) == {}, "no instances"
    # A bare application has no Go components, so it sets no [binary] and runs the bare kern; the
    # README shows how it builds its own binary once it has some (requirement 3).
    assert "binary" not in settings, "a bare application runs the bare kern"
    readme = (TEMPLATE / "README.md").read_text(encoding="utf-8")
    assert "Building your own binary" in readme and "kern-release.yml" in readme
    check = (TEMPLATE / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
    # The battery's copy `se new app` writes beside it at kern's pin (scripts/se_workflows.py).
    assert re.search(r"(?m)^  check:\n    uses: \./\.github/workflows/kern-battery\.yml$", check)
    main = (TEMPLATE / "cmd" / "app" / "main.go").read_text(encoding="utf-8")
    assert 'cli.Run("app", os.Args[1:], os.Stdout, os.Stderr)' in main


def test_the_template_keeps_trust_off_so_its_ci_runs_the_full_battery() -> None:
    """The template application leaves se.toml [tests] trust_integrator at its default, off: the
    battery's trust job answers false, and its check grants only contents: read and no schedule."""
    tests = tomllib.loads((TEMPLATE / "se.toml").read_text(encoding="utf-8"))["tests"]
    assert "trust_integrator" not in tests and "full_every" not in tests
    assert ci_trust.trust_settings(TEMPLATE).on is False
    check = workflow(TEMPLATE / ".github" / "workflows" / "check.yml")
    assert check["jobs"] == {"check": {"uses": "./.github/workflows/kern-battery.yml"}}
    assert check["permissions"] == {"contents": "read"}
    assert set(check["on"]) == {"pull_request", "push"}, "no nightly safety net: nothing is trusted"


def test_kerns_workflows_use_only_node_24_actions() -> None:
    for path in (RELEASE, BATTERY, ACTION):
        text = path.read_text(encoding="utf-8")
        uses = re.findall(r"uses: ([\w.-]+/[\w.-]+)@v(\d+)", text)
        assert uses, path
        for action, major in uses:
            assert action in NODE_24, f"{path.name}: {action} is not in NODE_24; add its Node 24 major"
            assert int(major) >= NODE_24[action], f"{path.name}: {action}@v{major} runs on Node 20"

def test_the_release_is_reusable_built_on_every_change_and_published_only_from_main() -> None:
    """kern's README "Release": a reusable workflow any application calls for its own binary; a
    pull request proves the build without publishing. kern's own release is kern's repository's."""
    release = workflow(RELEASE)
    assert set(release["on"]) == {"workflow_call"}, "kern's own triggers are kern's repository's"
    assert release["on"]["workflow_call"]["inputs"]["directory"]["default"] == "."
    assert list(release["jobs"]) == ["build", "publish"], "no template job: kern's battery runs in kern's CI"
    build = release["jobs"]["build"]
    names = [s.get("name") or s.get("uses") for s in build["steps"]]
    # kern is placed one way, by the action the battery calls too, for the checkout's se.lock.
    kern = step(build, "kern at the pin")
    assert kern == {"name": "kern at the pin", "uses": KERN_AT_PIN}, "the folder is the checkout's, the default"
    assert all("se.lock" not in str(s.get("run", "")) for s in build["steps"]), "no inline lock reader"
    go = step(build, "actions/setup-go")
    assert go["with"]["go-version-file"] == "${{ inputs.directory }}/go.mod"
    assert names.index("actions/checkout@v7") < names.index(kern["name"]) < names.index(go["uses"])
    plan, archives = step(build, "The release the folder names"), step(build, "Six binaries and SHA256SUMS")
    for each in (plan, archives):
        assert each["working-directory"] == "${{ inputs.directory }}", "kern's tool runs from the binary's module"
    assert plan["run"].startswith('go run kern/tools/release plan --dir . --repository "$GITHUB_REPOSITORY"')
    assert 'go run kern/tools/release build --dir . --out "$RUNNER_TEMP/dist"' in archives["run"]
    assert "sha256sum -c SHA256SUMS" in archives["run"]
    assert build["outputs"]["binary"] == "${{ steps.plan.outputs.binary }}", "the artifact and title carry the binary's name"
    publish = release["jobs"]["publish"]
    assert publish["needs"] == "build"
    assert "needs.build.result == 'success'" in publish["if"]
    assert "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'" in publish["if"]
    assert publish["permissions"] == {"contents": "write"} and "permissions" not in build
    # A release that exists is never changed.
    run = step(publish, "Publish the release where it is missing")["run"]
    assert run.index('gh release view "$TAG"') < run.index('gh release create "$TAG"')


def kern_at_pin(folder: Path, files: dict[str, str]) -> tuple[subprocess.CompletedProcess, str]:
    """Run the action kern-at-pin's step "The kern se.lock locks" for `folder`, holding `files`."""
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    output = folder.parent / f"{folder.name}.output"
    output.write_text("", encoding="utf-8")
    script = step(yaml.safe_load(ACTION.read_text(encoding="utf-8"))["runs"], "The kern se.lock locks")
    assert script["shell"] == "python3 {0}" and script["env"] == {"PYTHONUNBUFFERED": "1", "FOLDER": "${{ inputs.folder }}"}
    # The step's Python, run in this process as `python3 {0}` would run it: in the folder's parent,
    # with the step's environment, its exit code and output answered (tests/fake_processes.py).
    code = compile(script["run"], f"{KERN_AT_PIN}/action.yml", "exec")
    invocation = fake_processes.Invocation(["python3", "-c", "<step>"], {
        "cwd": folder.parent, "env": {**os.environ, "FOLDER": folder.name, "GITHUB_OUTPUT": str(output)}})
    answer = fake_processes.run_main(lambda _arguments: exec(code, {"__name__": "__main__"}), invocation)
    result = subprocess.CompletedProcess(invocation.argv, answer.returncode, answer.stdout.decode("utf-8"),
                                         answer.stderr.decode("utf-8"))
    return result, output.read_text(encoding="utf-8")


LOCKED = '[components.kern]\nversion = "0.14.1"\nref = "' + "a" * 40 + '"\n'
REQUIRES = "module se/components\n\nrequire (\n\tgolang.org/x/sys v0.41.0\n\tkern v{}\n)\n\nreplace kern => ../.se/modules/kern\n"
SE_PIN = '[components.kern]\ngo = "components/go.mod"\n'
APP_PIN = '[components.kern]\ngo = true\n'


def test_the_action_places_kern_at_the_commit_se_lock_locks_for_the_go_mod_se_toml_names(tmp_path) -> None:
    """SE's shape (go names components/go.mod) and an application's (go = true, its own go.mod)."""
    action = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    assert action["inputs"]["folder"]["default"] == "."
    checkout = step(action["runs"], "kern at the commit se.lock locks")
    assert checkout["if"] == "steps.lock.outputs.ref != ''"
    assert checkout["with"] == {"repository": "${{ github.repository_owner }}/kern",
                                "ref": "${{ steps.lock.outputs.ref }}", "path": "${{ steps.lock.outputs.path }}"}
    for name, files in (("se", {"se.toml": SE_PIN, "se.lock": LOCKED, "components/go.mod": REQUIRES.format("0.14.1")}),
                        ("app", {"se.toml": APP_PIN, "se.lock": LOCKED, "go.mod": REQUIRES.format("0.14.1")})):
        result, output = kern_at_pin(tmp_path / name, files)
        assert result.returncode == 0, result.stdout + result.stderr
        assert output == f"ref={'a' * 40}\npath={name}/.se/modules/kern\n"
        assert result.stdout == f"kern-at-pin: kern 0.14.1 at {'a' * 12} into {name}/.se/modules/kern\n"


def test_the_action_reads_a_require_above_major_1_as_go_spells_it(tmp_path, monkeypatch, capsys) -> None:
    """kern 2 is required as v2.1.0+incompatible (se_modules.go_version); the lock's version is
    2.1.0. The step's script runs in this process, its exit caught, so the test starts none."""
    folder = tmp_path / "se"
    locked = '[components.kern]\nversion = "2.1.0"\nref = "' + "c" * 40 + '"\n'
    for name, text in {"se.toml": SE_PIN, "se.lock": locked,
                       "components/go.mod": REQUIRES.format("2.1.0+incompatible")}.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    output = tmp_path / "output"
    output.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FOLDER", "se")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    script = step(yaml.safe_load(ACTION.read_text(encoding="utf-8"))["runs"], "The kern se.lock locks")["run"]
    try:
        exec(compile(script, str(ACTION), "exec"), {"__name__": "__main__"})
    except SystemExit as stop:
        assert not stop.code, capsys.readouterr().out
    assert output.read_text(encoding="utf-8") == f"ref={'c' * 40}\npath=se/.se/modules/kern\n"
    assert capsys.readouterr().out == f"kern-at-pin: kern 2.1.0 at {'c' * 12} into se/.se/modules/kern\n"


def test_the_action_refuses_a_lock_off_the_require_naming_both_lines(tmp_path) -> None:
    result, output = kern_at_pin(tmp_path / "off", {"se.toml": SE_PIN, "se.lock": LOCKED,
                                                    "components/go.mod": REQUIRES.format("0.15.0")})
    assert result.returncode == 1 and output == ""
    assert result.stdout == (
        '::error::kern-at-pin: off/se.lock [components.kern] version = "0.14.1" but off/components/go.mod says '
        "require kern v0.15.0: run se_modules.py sync kern and commit se.lock\n")
    result, _ = kern_at_pin(tmp_path / "unnamed", {"se.toml": '[components.kern]\n', "se.lock": LOCKED})
    assert result.returncode == 1 and "unnamed/se.toml [components.kern] names no go" in result.stdout


def test_the_action_leaves_a_folder_carrying_kerns_source_as_it_is(tmp_path) -> None:
    """An application made before kern left SE: its se.lock locks no kern, its kern/ carries kern."""
    for name, lock in (("none", {}), ("other", {"se.lock": '[components.obs]\nversion = "4.0.1"\nref = "' + "b" * 40 + '"\n'})):
        result, output = kern_at_pin(tmp_path / name, {"se.toml": APP_PIN, **lock, "kern/go.mod": "module kern\n",
                                                       "go.mod": "module app\n\nrequire kern v0.0.0\n\nreplace kern => ./kern\n"})
        assert result.returncode == 0 and output == "", result.stdout + result.stderr
        assert result.stdout == (f"kern-at-pin: {name}/se.lock locks no kern and {name}/kern/go.mod carries "
                                 "kern's source; nothing is placed\n")


def test_the_action_refuses_a_folder_with_neither_naming_the_sync(tmp_path) -> None:
    result, output = kern_at_pin(tmp_path / "bare", {"se.toml": APP_PIN, "go.mod": "module app\n\nrequire kern v0.14.1\n"})
    assert result.returncode == 1 and output == ""
    assert result.stdout == ("::error::kern-at-pin: bare/se.lock locks no kern and bare/kern/go.mod does not exist: "
                             "run se_modules.py sync kern and commit se.lock\n")


SE_RELEASE = PROJECT / ".github" / "workflows" / "se-release.yml"


def test_se_builds_its_own_binary_through_kerns_reusable_release() -> None:
    """Requirement: SE releases the `se` binary (core plus its Go components) through kern's reusable
    release workflow, with the se-v<version> tag scheme components/release.toml owns."""
    text = SE_RELEASE.read_text(encoding="utf-8")
    assert re.search(r"(?m)^    uses: \./\.github/workflows/kern-release\.yml\n", text)
    assert re.search(r"(?m)^    with:\n      directory: components\n", text)
    assert "contents: write\n" in text
    # It builds on a change to the binary's inputs, and proves the build on a pull request.
    for event in ("  pull_request:\n", "  push:\n"):
        assert event in text
    paths = ["components/**", "se.lock", "se.toml", ".github/workflows/se-release.yml",
             ".github/workflows/kern-release.yml", ".github/actions/kern-at-pin/action.yml"]
    release = workflow(SE_RELEASE)
    for event in ("pull_request", "push"):
        assert release["on"][event]["paths"] == paths, "the binary's inputs: its folder, the kern pin, the workflows"
    release = tomllib.loads((PROJECT / "components" / "release.toml").read_text(encoding="utf-8"))
    assert release["binary"] == "se" and release["package"] == "./cmd/se"
    assert release["download"] == "releases/download/se-v{version}", (
        "the se-v<version> tag scheme, distinct from SE's v<version>, under the home origin names")
