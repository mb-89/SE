"""kern, the Go core incubated under kern/ (kern/README.md "Tests"): the check main requires runs it."""

import re
import tomllib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT / ".github" / "workflows" / "check.yml"
# The first major of actions/setup-go that runs on Node 24.
SETUP_GO_NODE_24 = 6


def test_the_required_check_runs_kerns_vet_and_tests_on_the_go_its_go_mod_pins() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    jobs = workflow[workflow.index("\njobs:\n"):]
    assert re.findall(r"(?m)^  (\w[\w-]*):\n", jobs) == ["check", "kern-windows"], (
        "kern runs in the required job check, and on Windows in kern-windows, which check needs"
    )
    setups = re.findall(r"uses: actions/setup-go@v(\d+)\n        with:\n((?:          .*\n)+)", workflow)
    assert len(setups) == 2, "kern's steps set up Go on Windows and on Linux"
    for major, inputs in setups:
        assert int(major) >= SETUP_GO_NODE_24, "setup-go below v6 runs on Node 20"
        assert "go-version-file: kern/go.mod" in inputs and "cache-dependency-path: kern/go.sum" in inputs
    assert re.search(r"(?m)^go \d+\.\d+\.\d+$", (PROJECT / "kern" / "go.mod").read_text(encoding="utf-8"))
    # Go is set up before the suite step, which runs kern's tests as se.toml declares them.
    check = re.search(r"(?ms)^  check:\n(.*?)(?=^  \w|\Z)", jobs)[1]
    steps = ["actions/setup-go", "time go vet ./...", "scripts/work_tickets.py suite --worktree .",
             "needs.kern-windows.result"]
    assert [check.index(step) for step in steps] == sorted(check.index(step) for step in steps)
    assert "        working-directory: kern\n        run: time go vet ./...\n" in check
    assert "go test" not in check, "kern's tests have one declaration, se.toml [tests.beside.kern]"


def test_the_required_check_fails_unless_kern_passed_on_windows() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    jobs = workflow[workflow.index("\njobs:\n"):]
    windows = jobs[jobs.index("\n  kern-windows:\n"):]
    check = re.search(r"(?ms)^  check:\n(.*?)(?=^  \w|\Z)", jobs)[1]
    assert "    runs-on: windows-" in windows
    for command in ("go vet ./...", "go test ./..."):
        assert f"        working-directory: kern\n        run: {command}\n" in windows
    assert "work_tickets.py suite" not in windows, "the Python suite and its budget stay on Linux"
    assert "    needs: kern-windows\n" in check
    # A required check that is skipped counts as passed: check runs whatever kern-windows answered.
    assert "    if: ${{ !cancelled() }}\n" in check
    assert re.search(r'if \[ "\$WINDOWS" != success \]; then\n.*\n\s+exit 1', check), "check fails unless kern-windows passed"


RELEASE = PROJECT / ".github" / "workflows" / "kern-release.yml"
BATTERY = PROJECT / ".github" / "workflows" / "kern-battery.yml"
TEMPLATE = PROJECT / "kern" / "template"
# The first major of each action kern's workflows use that runs on Node 24.
NODE_24 = {"actions/checkout": 5, "actions/setup-go": SETUP_GO_NODE_24, "actions/upload-artifact": 6,
           "actions/download-artifact": 7, "astral-sh/setup-uv": 7}

def test_the_battery_holds_the_applications_tests_to_se_toml_tests() -> None:
    text = BATTERY.read_text(encoding="utf-8")
    assert "on:\n  workflow_call:\n" in text
    assert "go-version-file: ${{ inputs.directory }}/go.mod" in text
    assert "run: go vet ./..." in text
    assert 'tests.get("command"), tests.get("target_seconds"), tests.get("limit_seconds")' in text
    assert "if seconds > limit:" in text and "if seconds > target:" in text

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
    check = (TEMPLATE / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^  check:\n    uses: mb-89/SE/\.github/workflows/kern-battery\.yml@kern-v\d+\.\d+\.\d+$", check)
    version = tomllib.loads((PROJECT / "kern" / "release.toml").read_text(encoding="utf-8"))["version"]
    assert f"@kern-v{version}" in check, "the template calls the battery of the kern it is released with"
    main = (TEMPLATE / "cmd" / "app" / "main.go").read_text(encoding="utf-8")
    assert 'cli.Run("app", os.Args[1:], os.Stdout, os.Stderr)' in main


def test_kerns_workflows_use_only_node_24_actions() -> None:
    for path in (RELEASE, BATTERY):
        text = path.read_text(encoding="utf-8")
        uses = re.findall(r"uses: ([\w.-]+/[\w.-]+)@v(\d+)", text)
        assert uses, path
        for action, major in uses:
            assert action in NODE_24, f"{path.name}: {action} is not in NODE_24; add its Node 24 major"
            assert int(major) >= NODE_24[action], f"{path.name}: {action}@v{major} runs on Node 20"

def test_the_release_is_built_on_every_change_to_kern_and_published_only_from_main() -> None:
    """kern/README.md "Release": a pull request proves the build without publishing."""
    text = RELEASE.read_text(encoding="utf-8")
    paths = '["kern/**", ".github/workflows/kern-release.yml", ".github/workflows/kern-battery.yml"]'
    assert text.count(f"    paths: {paths}\n") == 2, "pull requests and pushes to main that touch kern"
    jobs = text[text.index("\njobs:\n"):]
    assert re.findall(r"(?m)^  (\w[\w-]*):\n", jobs) == ["build", "template", "publish"]
    build = re.search(r"(?ms)^  build:\n(.*?)(?=^  \w)", jobs)[1]
    assert 'go run ./tools/release plan --repository "$GITHUB_REPOSITORY"' in build
    assert 'go run ./tools/release build --out "$RUNNER_TEMP/dist"' in build
    assert "sha256sum -c SHA256SUMS" in build
    assert "    uses: ./.github/workflows/kern-battery.yml\n    with:\n      directory: kern/template\n" in jobs
    publish = jobs[jobs.index("\n  publish:\n"):]
    assert "    needs: [build, template]\n" in publish
    assert "    if: github.ref == 'refs/heads/main' && github.event_name != 'pull_request'\n" in publish
    assert "      contents: write\n" in publish and "contents: write" not in jobs[:jobs.index("\n  publish:\n")]
    # A release that exists is never changed.
    assert publish.index('gh release view "$TAG"') < publish.index('gh release create "$TAG"')

def test_the_release_toml_names_one_url_with_the_tag_while_kern_is_incubated() -> None:
    settings = tomllib.loads((PROJECT / "kern" / "release.toml").read_text(encoding="utf-8"))
    assert set(settings) == {"version", "download"}
    assert re.fullmatch(r"\d+\.\d+\.\d+", settings["version"])
    assert settings["download"] == "https://github.com/mb-89/SE/releases/download/kern-v{version}"
    readme = (PROJECT / "kern" / "README.md").read_text(encoding="utf-8")
    assert "**The move to `mb-89/kern` changes one URL:** `release.toml`'s `download`" in readme
