"""scripts/door_report.py: every reach outside a declared door, refused at its door's level, with no baseline.

Planted reaches are text written into fixture trees; the words that would make this file a reach of
SE's own doors are spelled in halves, as scripts/hygiene.py spells its markers, so neither hygiene nor
the report finds one here.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

import door_report
import hygiene
from door_report import Declaration, DeclarationError, Reach, declaration, load, load_all, main, reaches, scan
from positive_control import positive_control

ROOT = Path(__file__).resolve().parents[1]
DOORS = ROOT / "scripts" / "doors"
GIT = "gi" + "t"
GITHUB_API = "api.git" + "hub.com"
NEW_FILES = ("scripts/door_report.py", "tests/positive_control.py", "tests/test_door_report.py")
SUBPROCESS = "sub" + "process"

# One planted reach of each kind, for a made-up door.
WIDGET = Declaration(door="widget", commands=("tool",), imports=("widget", "example.com/widget"),
                     calls=("reach_out", "clock.read"), names=("vault.secrets",),
                     literals=("example.com/endpoint",))
PYTHON = (
    "import subprocess\n"
    "from widget.part import piece\n"
    "subprocess.run(['tool', 'x'])\n"
    "subprocess.run('tool status', shell=True)\n"
    "helper.reach_out(1)\n"
    "URL = 'https://example.com/endpoint/v1'\n"
    "feedback.reading('the tool', ['tool', 'y'])\n"
    "import widgetry\n"
    "when = my.clock.read()\n"
    "token = vault.secrets['key']\n"
    "read()\n"
    "secrets = 1\n"
)
GO = (
    "package tool\n"
    "import (\n"
    '\t"os/exec"\n'
    '\tw "example.com/widget/sub"\n'
    ")\n"
    'cmd := exec.CommandContext(ctx, "tool", "-x")\n'
    'var u = "see example.com/endpoint"\n'
    "reach_out()\n"
)


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def toml(door: str, level: str = "error", **lists: list[str]) -> str:
    return f'door = "{door}"\nlevel = "{level}"\n' + "".join(f"{key} = {value!r}\n" for key, value in lists.items())


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


# The finder


def test_one_planted_reach_of_each_kind_is_listed_with_its_kind_word_and_line():
    assert reaches("scripts/tool.py", PYTHON, WIDGET) == [
        Reach("scripts/tool.py", 2, "import", "widget"),
        Reach("scripts/tool.py", 3, "command", "tool"),
        Reach("scripts/tool.py", 4, "command", "tool"),
        Reach("scripts/tool.py", 5, "call", "reach_out"),
        Reach("scripts/tool.py", 6, "literal", "example.com/endpoint"),
        Reach("scripts/tool.py", 9, "call", "clock.read"),
        Reach("scripts/tool.py", 10, "name", "vault.secrets"),
    ]
    assert reaches("components/tool.go", GO, WIDGET) == [
        Reach("components/tool.go", 4, "import", "example.com/widget"),
        Reach("components/tool.go", 6, "command", "tool"),
        Reach("components/tool.go", 7, "literal", "example.com/endpoint"),
    ]


def test_a_reach_prints_as_path_line_kind_word():
    assert str(Reach("scripts/tool.py", 3, "command", "tool")) == "scripts/tool.py:3: command tool"


# The command on fixture trees


def test_a_git_list_outside_the_door_is_refused_and_inside_the_door_it_is_not(tmp_path, capsys):
    planted = f"import {SUBPROCESS}\n{SUBPROCESS}.run(['{GIT}', 'status'])\n"
    write(tmp_path, {"scripts/tool.py": planted, "scripts/git_door.py": planted})
    code, out, _ = run(capsys, "--root", str(tmp_path))
    assert code == 1
    assert f"door_report: scripts/tool.py:2: command {GIT} outside the {GIT} door" in out.splitlines()
    assert "scripts/git_door.py" not in out
    assert out.splitlines()[-1].startswith("door_report: refused (")


def test_a_program_started_outside_the_process_door_is_refused_and_through_it_passes(tmp_path, capsys):
    """The class the overhaul found (a script starting a program itself), held by one instance."""
    doors = write(tmp_path / "doors", {"process.toml": (DOORS / "process.toml").read_text(encoding="utf-8")})
    write(tmp_path / "root", {"scripts/tool.py": f"import {SUBPROCESS}\n{SUBPROCESS}.run(['go', 'build'])\n",
                              "scripts/fine.py": "import process_door\nprocess_door.run(['go', 'build'])\n",
                              "tests/test_tool.py": f"import {SUBPROCESS}\n{SUBPROCESS}.run(['go', 'build'])\n"})
    code, out, _ = run(capsys, "--root", str(tmp_path / "root"), "--doors", str(doors))
    assert code == 1
    assert [line for line in out.splitlines() if " outside the " in line] == [
        f"door_report: scripts/tool.py:2: call {SUBPROCESS}.run outside the process door"], \
        "a test's start is the spawn guard's, so the process door's ground is the code that runs"


def test_a_door_at_warn_counts_its_reaches_on_one_line_and_passes_and_list_names_each(tmp_path, capsys):
    doors = write(tmp_path / "doors", {"a.toml": toml("a", "warn", commands=["tool"])})
    write(tmp_path / "root", {"scripts/tool.py": "x = ['tool']\ny = ['tool']\n", "scripts/two.py": "z = ['tool']\n"})
    code, out, _ = run(capsys, "--root", str(tmp_path / "root"), "--doors", str(doors))
    assert code == 0
    assert out.splitlines() == [
        "door_report: warning: a: 3 reach(es) in 2 file(s) outside the door, level warn while they move behind it "
        "(door_report.py --list names each)",
        f"door_report: passed (1 doors) in {tmp_path / 'root'}"]
    code, out, _ = run(capsys, "--root", str(tmp_path / "root"), "--doors", str(doors), "--list")
    assert code == 0
    assert "door_report: warning: scripts/tool.py:2: command tool" in out.splitlines()


def test_a_door_at_warn_with_no_reach_left_is_refused_naming_the_step_to_error(tmp_path, capsys):
    doors = write(tmp_path / "doors", {"a.toml": toml("a", "warn", commands=["tool"])})
    write(tmp_path / "root", {"scripts/tool.py": "x = 1\n"})
    code, out, _ = run(capsys, "--root", str(tmp_path / "root"), "--doors", str(doors))
    assert code == 1
    assert out.splitlines()[0] == ('door_report: a: no reach left outside the door at level warn: '
                                   'set level = "error" in scripts/doors/a.toml')


def test_the_ground_is_hygienes_and_a_contract_test_is_its_doors(tmp_path, capsys):
    doors = write(tmp_path / "doors", {"a.toml": toml("a", files=["scripts/door.py"], literals=["needle"],
                                                       contract_tests=["tests/test_door.py"])})
    needle = "x = 'needle'\n"
    write(tmp_path / "root", {name: needle for name in (
        "scripts/door.py", "tests/test_door.py", "tests/test_other.py", "components/c.py", "components/k.go",
        "scripts/notes.md", "scripts/.venv/v.py", "tests/testdata/t.py", "scripts/__pycache__/p.py", "docs/d.py",
        "kern/k.go", ".se/modules/kern/k.go")})
    write(tmp_path / "root", {"components/k.go": 'var x = "needle"\n'})
    code, out, _ = run(capsys, "--root", str(tmp_path / "root"), "--doors", str(doors))
    assert code == 1
    assert [line for line in out.splitlines() if ": literal " in line] == [
        "door_report: components/c.py:1: literal needle outside the a door",
        "door_report: components/k.go:1: literal needle outside the a door",
        "door_report: tests/test_other.py:1: literal needle outside the a door"], "kern's code is kern's repository's to scan"


def test_a_doors_ground_narrows_the_folders_it_checks(tmp_path, capsys):
    doors = write(tmp_path / "doors", {"a.toml": toml("a", ground=["scripts"], literals=["needle"])})
    write(tmp_path / "root", {"scripts/s.py": "x = 'needle'\n", "tests/t.py": "x = 'needle'\n"})
    code, out, _ = run(capsys, "--root", str(tmp_path / "root"), "--doors", str(doors))
    assert code == 1
    assert [line for line in out.splitlines() if ": literal " in line] == [
        "door_report: scripts/s.py:1: literal needle outside the a door"]


def test_a_file_that_does_not_parse_or_is_not_utf8_is_refused_as_no_door_can_check_it(tmp_path, capsys):
    write(tmp_path, {"scripts/broken.py": "def (:\n", "scripts/fine.py": "x = 1\n"})
    (tmp_path / "scripts" / "latin.py").write_bytes(b"x = '\xe9'\n")
    code, out, _ = run(capsys, "--root", str(tmp_path))
    assert code == 1
    lines = out.splitlines()
    assert lines[0].startswith("door_report: scripts/broken.py: not read (SyntaxError")
    assert lines[0].endswith("so no door can check it")
    assert lines[1].startswith("door_report: scripts/latin.py: not read (UnicodeDecodeError")


# Declarations


@pytest.mark.parametrize(("text", "key"), [
    ('door = "a"\nlevel = "warn"\nwords = ["x"]\n', "'words'"),
    ('door = "a"\nlevel = "warn"\n[baseline]\n"scripts/x.py" = { count = 1, reason = "why" }\n',
     "a door keeps no baseline"),
    ('door = "a"\n', "'level'"),
    ('door = "a"\nlevel = "report"\n', "'level'"),
    ('door = "a"\nlevel = "error"\nground = ["docs"]\n', "'ground'"),
])
def test_a_bad_declaration_is_refused_with_its_file_and_key_and_the_command_exits_2(tmp_path, capsys, text, key):
    doors = write(tmp_path / "doors", {"bad.toml": text})
    with pytest.raises(DeclarationError) as refused:
        load(doors / "bad.toml")
    assert "bad.toml" in str(refused.value) and key in str(refused.value)
    code, out, err = run(capsys, "--root", str(tmp_path), "--doors", str(doors))
    assert (code, out) == (2, "")
    assert "bad.toml" in err and key in err


def test_a_folder_without_declarations_and_a_file_that_is_not_toml_exit_2(tmp_path, capsys):
    assert run(capsys, "--root", str(tmp_path), "--doors", str(tmp_path))[0] == 2
    write(tmp_path / "doors", {"a.toml": "door = \n"})
    code, _, err = run(capsys, "--root", str(tmp_path), "--doors", str(tmp_path / "doors"))
    assert code == 2 and "a.toml: not read" in err


def test_ses_declarations_load_and_name_existing_paths():
    doors = {door.door: door for door in load_all(DOORS)}
    assert sorted(doors) == ["clock", "environment", GIT, "github", "mcp", "network", "process", "shell"]
    for door in doors.values():
        named = [*door.files, *door.contract_tests]
        assert [path for path in named if not (ROOT / Path(path)).is_file()] == [], door.door


def test_ses_tree_passes_the_door_check(capsys):
    """Every door at error finds no reach on SE's own tree, and every door at warn still finds one."""
    assert run(capsys, "--root", str(ROOT))[0] == 0


def test_the_git_declaration_is_hygienes_git_door():
    git = load(DOORS / f"{GIT}.toml")
    assert sorted(git.files) == sorted(hygiene.GIT_DOOR)
    assert git.commands == (GIT,)
    assert git.level == "error" and hygiene.GIT_ALLOWED == {}
    assert sorted(git.contract_tests) == ["tests/test_git_door.py"]


def test_the_declaration_refuses_a_list_that_is_not_strings():
    with pytest.raises(DeclarationError, match="'files'"):
        declaration("x.toml", {"door": "a", "level": "warn", "files": "scripts/a.py"})


# The same reaches as hygiene


def hygiene_git_lines(root: Path) -> dict[str, list[int]]:
    """hygiene's git subprocess lines outside GIT_DOOR, per file, over its own ground."""
    found = {}
    for folder in hygiene.GIT_SCANNED:
        for path in sorted((root / folder).rglob("*")):
            name = path.relative_to(root).as_posix()
            if path.suffix in (".py", ".go") and path.is_file() and name not in hygiene.GIT_DOOR \
                    and not {".venv", "testdata", "__pycache__"} & set(path.parts):
                if lines := hygiene.git_subprocess_lines(path):
                    found[name] = lines
    return found


def report_git_lines(root: Path) -> dict[str, list[int]]:
    texts, unread = door_report.read(root)
    assert unread == {}
    (result,), unparsed = scan(texts, [load(DOORS / f"{GIT}.toml")])
    assert unparsed == {}
    found: dict[str, list[int]] = {}
    for reach in result.reaches:
        found.setdefault(reach.path, []).append(reach.line)
    return found


def test_the_git_reaches_equal_hygienes_on_the_tree_of_its_git_door_test(tmp_path):
    write(tmp_path, {
        "scripts/tool.py": (
            "import subprocess\n"
            f"feedback.reading('the remote', ['{GIT}', 'fetch'])\n"
            f"subprocess.run(['{GIT}', '-C', root, 'status'])\n"
            f"subprocess.run('{GIT} status', shell=True)\n"
            "git_door.run('status', root=root)\n"),
        "components/tool.go": f'cmd := exec.CommandContext(ctx, "{GIT}", "-C", dir)\n',
        "scripts/git_door.py": f"subprocess.run(['{GIT}', *argv])\n",
        "tests/testdata/skipped.py": f"subprocess.run(['{GIT}', 'log'])\n",
    })
    report = report_git_lines(tmp_path)
    assert report == hygiene_git_lines(tmp_path) == {"components/tool.go": [1], "scripts/tool.py": [3, 4]}
    assert sorted(hygiene.git_door_findings(tmp_path, {})) == [
        f"{name}:{lines[0]}: {len(lines)} {GIT} subprocess(es) outside the door, 0 allowed; run {GIT} through "
        "scripts/git_door.py (tests: the fake_git_door fixture)" for name, lines in report.items()]


def test_on_ses_tree_after_the_positive_control_the_git_reaches_equal_hygienes_and_no_new_file_is_a_reach(
        tmp_path):
    """One scan of a copy of the folders hygiene and the report scan: the control's planted git list
    is found first, then the report's git reaches equal hygiene's, and the new files hold no reach of
    any of SE's doors."""
    for folder in door_report.SCANNED:
        shutil.copytree(ROOT / folder, tmp_path / folder, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
    planted = "scripts/planted_by_the_control.py"
    doors = load_all(DOORS)
    results: dict[str, list[Reach]] = {}

    def sweep(root: Path) -> list[tuple[str, int]]:
        texts, unread = door_report.read(root)
        found, unparsed = scan(texts, doors)
        assert unread == unparsed == {}
        results.update((result.door.door, result.reaches) for result in found)
        return [(reach.path, reach.line) for reach in results[GIT]]

    positive_control("door_report git", sweep, tmp_path, planted,
                     f"import subprocess\nsubprocess.run(['{GIT}', 'status'])\n", (planted, 2))
    report: dict[str, list[int]] = {}
    for reach in results[GIT]:
        report.setdefault(reach.path, []).append(reach.line)
    assert report == hygiene_git_lines(tmp_path) == {planted: [2]}
    assert [str(reach) for found in results.values() for reach in found if reach.path in NEW_FILES] == []


def test_the_github_literal_is_found_in_its_halves_only_when_joined():
    github = load(DOORS / "github.toml")
    assert reaches("scripts/a.py", f"API = 'https://{GITHUB_API}'\n", github) == [
        Reach("scripts/a.py", 1, "literal", GITHUB_API)]
    assert reaches("scripts/a.py", "API = 'https://api.git' + 'hub.com'\n", github) == []


# The positive control


def test_the_positive_control_fails_on_a_sweep_that_finds_nothing_naming_the_sweep_and_the_member(tmp_path):
    with pytest.raises(pytest.fail.Exception) as failed:
        positive_control("a sweep", lambda root: [], tmp_path, "scripts/x.py", "x = 1\n", ("scripts/x.py", 1))
    assert "a sweep" in str(failed.value) and "scripts/x.py" in str(failed.value)


def test_the_positive_control_returns_what_the_sweep_found(tmp_path):
    found = positive_control("files", lambda root: sorted(p.name for p in root.rglob("*.py")),
                             tmp_path, "scripts/x.py", "x = 1\n", "x.py")
    assert found == ["x.py"]


# Thin wiring


def imported(source: str) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_check_imports_nothing_that_reaches_outside():
    names = imported((ROOT / "scripts" / "door_report.py").read_text(encoding="utf-8"))
    assert names & {"hygiene", "git_door", SUBPROCESS, "urllib", "socket", "http", "requests"} == set()


def test_the_import_check_finds_an_import():
    assert imported("from hygiene import x\nimport urllib.request as u\n") == {"hygiene", "urllib"}
