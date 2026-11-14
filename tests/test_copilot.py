"""SE under GitHub Copilot (scripts/copilot.py, scripts/copilot_smoke.sh, docs/copilot.md): the
install's merge, pin and ignore; the marketplace `se@se` names; the self-test's static checks over
this checkout; and the smoke verdict over its fixture, with `skipped` apart from `failed`. The
install through setup.sh and setup.ps1 is tested beside the other setup tests
(tests/test_public_check.py)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

import copilot
import se_plugin

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "copilot"
SYNTHETIC = FIXTURES / "smoke.synthetic.jsonl"
RECORDED = FIXTURES / "smoke.jsonl"


def test_settings_merge_keeps_every_other_key() -> None:
    existing = {"model": "x", "enabledPlugins": {"a@b": False},
                "extraKnownMarketplaces": {"b": {"source": {"source": "github", "repo": "o/b"}}}}
    merged = copilot.settings(existing)
    assert merged == {"model": "x",
                      "enabledPlugins": {"a@b": False, "se@se": True},
                      "extraKnownMarketplaces": {"b": {"source": {"source": "github", "repo": "o/b"}},
                                                 "se": {"source": {"source": "github", "repo": "mb-89/SE"}}}}
    assert existing["enabledPlugins"] == {"a@b": False}


def test_install_writes_the_settings_file_then_leaves_it_alone(tmp_path: Path) -> None:
    synced = []
    assert copilot.install(tmp_path, synced.append) == 0
    path = tmp_path / ".github" / "copilot" / "settings.json"
    first = path.read_text(encoding="utf-8")
    assert json.loads(first) == {"extraKnownMarketplaces": {"se": {"source": {"source": "github",
                                                                              "repo": "mb-89/SE"}}},
                                 "enabledPlugins": {"se@se": True}}
    assert copilot.install(tmp_path, synced.append) == 0
    assert path.read_text(encoding="utf-8") == first
    assert synced == [tmp_path.resolve()] * 2


def test_install_refuses_a_settings_file_it_cannot_read_and_writes_nothing(tmp_path: Path,
                                                                           capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / ".github" / "copilot" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert copilot.install(tmp_path, None) == 2
    assert path.read_text(encoding="utf-8") == "{not json"
    assert not (tmp_path / "se.toml").exists()
    assert "fix or remove it" in capsys.readouterr().err


def test_install_pins_se_as_a_range_and_keeps_an_existing_pin(tmp_path: Path) -> None:
    (tmp_path / "se.toml").write_text('[project]\nversion = "1.0.0"', encoding="utf-8")
    assert copilot.install(tmp_path, None) == 0
    data = tomllib.loads((tmp_path / "se.toml").read_text(encoding="utf-8"))
    assert data["project"] == {"version": "1.0.0"}
    assert data["modules"]["se"] == {"url": "https://github.com/mb-89/SE.git", "version": copilot.version_range()}
    pinned = 'url = "https://github.com/mb-89/SE.git"\nref = "' + "a" * 40 + '"\n'
    (tmp_path / "se.toml").write_text("[modules.se]\n" + pinned, encoding="utf-8")
    assert copilot.install(tmp_path, None) == 0
    assert (tmp_path / "se.toml").read_text(encoding="utf-8") == "[modules.se]\n" + pinned


def test_the_range_admits_this_se() -> None:
    version = tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert copilot.version_range() == "^" + ".".join(version.split(".")[:2])


@pytest.mark.parametrize("existing", ["", "build/", "build/\n.se\n"])
def test_install_ignores_se_once(tmp_path: Path, existing: str) -> None:
    (tmp_path / ".gitignore").write_text(existing, encoding="utf-8")
    for _ in range(2):
        assert copilot.install(tmp_path, None) == 0
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert sum(line in {".se", ".se/"} for line in lines) == 1
    assert lines[:len(existing.splitlines())] == existing.splitlines()


def test_a_failed_sync_names_the_command_to_run_again(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert copilot.install(tmp_path, lambda repo: 3) == 1
    assert "se_modules.py --root" in capsys.readouterr().err


def test_ses_own_checkout_installs_nothing(capsys: pytest.CaptureFixture) -> None:
    assert copilot.install(ROOT, None) == 0
    assert "needs nothing installed" in capsys.readouterr().out


def test_the_marketplace_se_at_se_names_is_generated() -> None:
    path = se_plugin.MANIFESTS[1]
    generated = json.loads(se_plugin.expected()[path])
    assert json.loads((ROOT / path).read_text(encoding="utf-8")) == generated
    assert copilot.PLUGIN_KEY == f"{generated['plugins'][0]['name']}@{generated['name']}" == "se@se"
    assert generated["plugins"][0]["source"] == "./"


def test_the_self_tests_static_checks_pass_on_this_checkout() -> None:
    report = copilot.Report([])
    copilot.check_hooks(ROOT, report)
    assert report.lines and report.lines[0].startswith("passed hooks:"), report.lines


def test_the_self_test_runs_beside_the_suite_with_its_own_budget() -> None:
    beside = tomllib.loads((ROOT / "se.toml").read_text(encoding="utf-8"))["tests"]["beside"]
    assert beside["copilot-self-test"]["command"][-2:] == ["self-test", "--build"]


def test_the_synthetic_fixture_is_marked_until_a_real_run_is_recorded() -> None:
    first = json.loads(SYNTHETIC.read_text(encoding="utf-8").splitlines()[0])
    assert first["synthetic"] is True
    if RECORDED.exists():
        assert "synthetic" not in RECORDED.read_text(encoding="utf-8").splitlines()[0]


@pytest.mark.parametrize("fixture", [path for path in (SYNTHETIC, RECORDED) if path.exists()],
                         ids=lambda path: path.name)
def test_the_smoke_helper_passes_its_fixture(fixture: Path) -> None:
    passed, detail = copilot.smoke_verdict(fixture.read_text(encoding="utf-8").splitlines())
    assert passed, detail
    assert "started:" in detail
    assert "status" in detail


def _without(lines: list[str], text: str) -> list[str]:
    return [line for line in lines if text not in line]


@pytest.mark.parametrize(("change", "reason"), [
    (lambda lines: _without(lines, "started:"), "no greeting"),
    (lambda lines: _without(lines, "se-status"), "no call of an se tool"),
    (lambda lines: [line.replace('"success": true', '"success": false') for line in lines], "se tool call failed: status"),
    (lambda lines: [line.replace('"exitCode": 0', '"exitCode": 1') for line in lines], "copilot exited 1"),
    (lambda lines: lines + ["not json"], "is no JSON"),
])
def test_the_smoke_helper_fails_naming_what_is_missing(change, reason: str) -> None:
    passed, detail = copilot.smoke_verdict(change(SYNTHETIC.read_text(encoding="utf-8").splitlines()))
    assert not passed
    assert reason in detail


def test_the_smoke_helper_reads_vs_codes_and_claudes_tool_names_too() -> None:
    for name in ("se/status", "mcp__se__status"):
        lines = [json.dumps({"type": "assistant.message", "data": {"content": "SE 1.2.3 started: x"}}),
                 json.dumps({"type": "tool", "data": {"name": name, "success": True}})]
        assert copilot.smoke_verdict(lines) == (True, "greeting `SE 1.2.3 started:` and se tool status answered")


def test_the_smoke_script_reports_skipped_without_a_token(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash")
    env = {key: value for key, value in os.environ.items() if key != "COPILOT_GITHUB_TOKEN"}
    done = subprocess.run([bash, str(ROOT / "scripts" / "copilot_smoke.sh")], capture_output=True, text=True,
                          env=env, check=False)
    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stdout == "copilot smoke: skipped: COPILOT_GITHUB_TOKEN is not set\n"
    assert "failed" not in done.stdout


def test_the_smoke_script_runs_the_pinned_cli_with_the_issues_flags() -> None:
    text = (ROOT / "scripts" / "copilot_smoke.sh").read_text(encoding="utf-8")
    assert 'version="1.0.112"' in text
    assert ("COPILOT_AUTO_UPDATE=false npx --yes \"@github/copilot@$version\" --plugin-dir=. --agent se -p status \\\n"
            "  --output-format json --allow-tool='se' --no-ask-user --trust-folder") in text
