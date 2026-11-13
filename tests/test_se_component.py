"""Tests of `se component add`: it scaffolds an ad hoc component under the ignored .se/components/
and places it in the overlay wiring (docs/go-core.md "Scripts are ad hoc, components are
long-term")."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import se
import se_component

ROOT = Path(__file__).resolve().parents[1]


def test_add_scaffolds_the_files_and_places_the_instance_in_the_overlay(tmp_path: Path):
    lines = se_component.add(tmp_path, "probe")
    toml = tmp_path / ".se" / "components" / "probe" / "component.toml"
    init = tmp_path / ".se" / "components" / "probe" / "__init__.py"
    assert toml.exists() and init.exists()
    assert 'name = "probe"' in toml.read_text(encoding="utf-8")
    assert '[commands."probe run"]' in toml.read_text(encoding="utf-8")
    overlay = (tmp_path / ".se" / "wiring.toml").read_text(encoding="utf-8")
    assert '[instances."probe"]' in overlay
    assert '"run-adhoc", "probe"' in overlay
    assert any("Scaffolded the ad hoc component probe" in line for line in lines)


def test_add_appends_a_second_component_to_the_overlay(tmp_path: Path):
    se_component.add(tmp_path, "one")
    se_component.add(tmp_path, "two")
    overlay = (tmp_path / ".se" / "wiring.toml").read_text(encoding="utf-8")
    assert '[instances."one"]' in overlay and '[instances."two"]' in overlay


@pytest.mark.parametrize("name", ["Probe", "1probe", "pro_be", "pro be", ""])
def test_add_refuses_a_name_that_is_not_lower_case_letters_digits_and_dashes(tmp_path: Path, name):
    with pytest.raises(se_component.ComponentError, match="no component name"):
        se_component.add(tmp_path, name)
    assert not (tmp_path / ".se" / "components").exists()


def test_add_refuses_a_component_that_already_exists(tmp_path: Path):
    se_component.add(tmp_path, "probe")
    with pytest.raises(se_component.ComponentError, match="already"):
        se_component.add(tmp_path, "probe")


def test_the_scaffolded_component_is_a_valid_kern_component_that_answers_its_command(tmp_path: Path):
    """The scaffold is a Python component over NATS: kern's SDK reads its declaration and the fake
    core runs its command, as the contract suite runs tally."""
    se_component.add(tmp_path, "my-probe")
    sys.path.insert(0, str(ROOT / "kern" / "python"))
    try:
        from kern import declaration
        from kern.fake import Fake

        folder = tmp_path / ".se" / "components" / "my-probe"
        decl = declaration.read(folder)
        assert decl.name == "my-probe" and "my-probe run" in decl.commands
        spec = importlib.util.spec_from_file_location("adhoc_my_probe", folder / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(folder.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(folder.parent))
        fake = Fake(module.my_probe)
        assert fake.run("my-probe run", "hi", "there") == "ad hoc my-probe ran: hi there"
    finally:
        sys.path.remove(str(ROOT / "kern" / "python"))


def test_se_component_add_runs_through_the_se_command(tmp_path: Path, capsys):
    assert se.main(["component", "add", "probe", "--root", str(tmp_path)]) == 0
    assert (tmp_path / ".se" / "components" / "probe" / "component.toml").exists()
    assert "Scaffolded the ad hoc component probe" in capsys.readouterr().out


def test_se_component_add_reports_the_error_and_fails(tmp_path: Path, capsys):
    assert se.main(["component", "add", "Bad", "--root", str(tmp_path)]) == 1
    assert "se component add:" in capsys.readouterr().err
