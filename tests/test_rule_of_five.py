"""The rule of five (scripts/rule_of_five.py, rule book doc-006): a crowded surface is refused at
`error` and warned about at `warn`, a `warn` with nothing left is refused, naming the step to
`error`, and SE's own checkout passes its level. Files only: no git, no network, no process."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hygiene  # noqa: E402
import rule_of_five  # noqa: E402


def surface(folder: Path, files: int, folders: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for number in range(files):
        (folder / f"file{number}.md").write_text("x\n", encoding="utf-8")
    for number in range(folders):
        (folder / f"folder{number}").mkdir()
    return folder


def settings(root: Path, text: str) -> None:
    (root / "se.toml").write_text(text, encoding="utf-8")


def test_a_surface_of_five_files_and_five_folders_passes_and_dot_entries_are_not_counted(tmp_path, capsys):
    surface(tmp_path, 5, 5)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".gitignore").write_text("x\n", encoding="utf-8")
    surface(tmp_path / "folder0", 9, 0)  # not a surface: only the root, spec/ and src/ are
    assert rule_of_five.main(["check", "--root", str(tmp_path)]) == 0
    assert "passed at level error" in capsys.readouterr().out


def test_a_crowded_root_spec_and_src_are_refused_at_the_default_level(tmp_path, capsys):
    surface(tmp_path, 6, 0)
    surface(tmp_path / "spec", 0, 6)
    surface(tmp_path / "src", 2, 2)
    assert rule_of_five.main(["check", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    # The root holds spec/ and src/ too, so two folders beside its six files.
    assert ("rule_of_five.py: the root holds 6 visible files (file0.md, file1.md, file2.md, file3.md, "
            "file4.md, file5.md); at most 5 of each (rule book doc-006)") in out
    assert "rule_of_five.py: spec/ holds 6 visible folders (folder0, folder1" in out
    assert "src/" not in out


def test_the_fix_of_one_crowded_root_passes(tmp_path):
    """One instance of the class: moving a sixth root file into a folder makes the root pass."""
    surface(tmp_path, 6, 0)
    assert rule_of_five.check(tmp_path, rule_of_five.Settings())[1]
    (tmp_path / "docs").mkdir()
    (tmp_path / "file5.md").rename(tmp_path / "docs" / "file5.md")
    assert rule_of_five.check(tmp_path, rule_of_five.Settings()) == ([], [])


def test_warn_prints_each_crowded_surface_and_passes(tmp_path, capsys):
    surface(tmp_path, 7, 0)
    settings(tmp_path, '[rule_of_five]\nlevel = "warn"\n')
    assert rule_of_five.main(["check", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "rule_of_five.py: warning: the root holds 8 visible files" in out
    assert "passed at level warn" in out


def test_warn_with_no_crowded_surface_left_is_refused_naming_the_step_to_error(tmp_path, capsys):
    surface(tmp_path, 1, 0)
    settings(tmp_path, '[rule_of_five]\nlevel = "warn"\n')
    assert rule_of_five.main(["check", "--root", str(tmp_path)]) == 1
    assert ('no crowded surface left at level warn: set level = "error" in se.toml [rule_of_five]'
            in capsys.readouterr().out)


def test_surfaces_a_project_names_replace_the_default_ones(tmp_path):
    surface(tmp_path / "spec", 6, 0)
    surface(tmp_path / "app", 6, 0)
    settings(tmp_path, '[rule_of_five]\nsurfaces = ["app"]\n')
    assert rule_of_five.check(tmp_path, rule_of_five.settings(tmp_path))[1] == [
        "app/ holds 6 visible files (file0.md, file1.md, file2.md, file3.md, file4.md, file5.md); "
        "at most 5 of each (rule book doc-006)"]


@pytest.mark.parametrize("table, problem", [
    ('level = "off"', "level must be one of warn, error"),
    ("baseline = 3", "unknown key(s) baseline"),
    ("surfaces = []", "surfaces must be a non-empty array of paths"),
])
def test_a_setting_it_cannot_run_from_is_a_setup_error(tmp_path, capsys, table, problem):
    settings(tmp_path, f"[rule_of_five]\n{table}\n")
    assert rule_of_five.main(["check", "--root", str(tmp_path)]) == 2
    assert problem in capsys.readouterr().err


def test_ses_checkout_passes_the_rule_of_five_at_its_level(capsys):
    assert hygiene.five_findings(ROOT) == []
