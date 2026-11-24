"""Code templates (docs/templates.md "Code templates"): templates of the one engine whose kind is
`code`, an adapter whose lines hold the shape and whose body holds the files `templates.py scaffold`
writes; the claimed scripts and modules are held to that shape by the check and by SE's gate."""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import re
import sys
from pathlib import Path

import pytest

import code_templates
import se_component
import se_script
import se_templates
import templates

ROOT = Path(__file__).resolve().parents[1]
CATALOG = templates.load(ROOT, tree=True)
CODE = sorted(name for name, template in CATALOG.items() if template.kind == templates.CODE)

pytestmark = pytest.mark.usefixtures("fake_git_door")


def scaffolded(name: str, path: Path, says: str = "Count the words it is given.") -> dict[Path, str]:
    return code_templates.scaffold(CATALOG[name], path, says)


def findings(text: str, relative: str) -> list[str]:
    """The refusing findings of `text` at `relative`, as the check and the gate read it."""
    return se_templates.refusals(CATALOG, ROOT, relative, text)[1]


def test_se_ships_the_code_templates_each_an_adapter_whose_body_is_its_files():
    assert CODE == ["go-module", "python-component", "python-module", "python-script"]
    for name in CODE:
        template = CATALOG[name]
        assert template.is_adapter and template.is_file and template.adapter["lines"] and template.code
        assert "code" in template.tags


def test_a_scaffolded_python_script_runs_prints_its_help_and_logs_with_only_its_slot_to_fill(
        tmp_path, capsys, monkeypatch):
    """Acceptance 1: the script the scaffold writes passes its template, prints its help with the
    logging line, and runs through se_script.run, which logs; uv runs it by its first line."""
    path = tmp_path / "scripts" / "new_thing.py"
    [(written, text)] = scaffolded("python-script", path).items()
    assert written == path
    assert text.splitlines()[:3] == ["#!/usr/bin/env -S uv run python", "# se:template se/python-script 1.0.0",
                                     '"""Count the words it is given.']
    assert findings(text, "scripts/new_thing.py") == []
    assert text.lower().count("slot") >= 4
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("new_thing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit) as stop:
        module.main(["--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: new_thing.py [-h] [words ...]") and "Count the words it is given." in out
    assert " ".join(se_script.LOG_HELP.split()) in " ".join(out.split())
    monkeypatch.setattr(sys, "argv", ["new_thing.py", "a", "b"])
    root = logging.getLogger()
    handlers = list(root.handlers)
    try:
        assert se_script.run(module.main, {se_script.LEVEL_VARIABLE: "debug"}) == 0
        captured = capsys.readouterr()
        assert captured.out == "a b\n"
        assert "new_thing.py: DEBUG: start: a b" in captured.err and "new_thing.py: DEBUG: exit 0 after" in captured.err
        assert "new_thing: INFO: new_thing: 2 words" in captured.err
    finally:
        root.handlers[:] = handlers


def test_a_scaffolded_go_module_names_its_files_by_the_module_and_its_go_mod_passes(tmp_path):
    """Acceptance 2's files: go.mod, the package and its test, each marked; go.mod passes the
    template that claims it (the module builds and tests green: the field report's evidence)."""
    made = scaffolded("go-module", tmp_path / "word-count")
    assert sorted(path.name for path in made) == ["go.mod", "wordcount.go", "wordcount_test.go"]
    for text in made.values():
        assert text.startswith("// se:template se/go-module 1.0.0\n")
    go_mod = made[tmp_path / "word-count" / "go.mod"]
    assert "\nmodule wordcount\n" in go_mod and findings(go_mod, "word-count/go.mod") == []
    assert "package wordcount\n" in made[tmp_path / "word-count" / "wordcount.go"]
    assert findings(go_mod, "go.mod") == []


@pytest.mark.parametrize("name", ["python-script", "python-module"])
def test_a_script_without_each_line_of_its_shape_is_refused_naming_that_line(name, tmp_path):
    """Requirement 7: the check refuses a script or module that lacks its marker or has lost a line
    of its shape (the uv entry, the library, the help, the entry through se_script.run)."""
    template = CATALOG[name]
    [text] = scaffolded(name, tmp_path / "thing.py").values()
    for line in template.adapter["lines"]:
        kept = "".join(item for item in text.splitlines(keepends=True)
                       if re.fullmatch(line["pattern"], item.strip()) is None)
        found = findings(kept, "scripts/thing.py")
        assert found, line["says"]
        if "marker" not in line["says"]:
            assert any(line["says"] in item for item in found), (line["says"], found)
    unmarked = findings("#!/usr/bin/env python3\nprint(1)\n", "scripts/thing.py")
    assert unmarked == ["scripts/thing.py (no template): body: scripts/thing.py: no template takes this file; "
                        "it carries no template marker: scaffold it, templates.py scaffold <template> --path "
                        "scripts/thing.py --says <one line> (one of python-module, python-script)"]
    moved = text.replace(f"/{name} 1.0.0", f"/{name} 2.0.0")
    assert any("template marker" in item for item in findings(moved, "scripts/thing.py"))


def test_every_one_of_ses_scripts_and_its_go_module_carries_its_template_and_shape():
    """Requirement 7 and acceptance 5: the shape check passes on all of SE's scripts and on its go.mod."""
    claimed = [path for path in sorted((ROOT / "scripts").glob("*.py")) if path.is_file()]
    claimed.append(ROOT / "components" / "go.mod")
    assert len(claimed) > 70
    refused = {path.relative_to(ROOT).as_posix(): found for path in claimed
               if (found := findings(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix()))}
    assert refused == {}
    kinds = {path.name: templates.select(CATALOG, templates.FILE_ACTION, path.read_text(encoding="utf-8"),
                                         path=path.relative_to(ROOT).as_posix()).template.name
             for path in claimed}
    assert kinds["work_tickets.py"] == "python-script" and kinds["se_script.py"] == "python-module"
    assert kinds["go.mod"] == "go-module"


def test_scaffold_writes_new_files_only_and_checks_its_arguments(tmp_path, capsys):
    path = tmp_path / "scripts" / "new_thing.py"
    arguments = ["scaffold", "python-script", "--path", str(path), "--says", "Echo.", "--root", str(tmp_path),
                 "--templates", str(ROOT / "templates")]
    assert templates.main(arguments) == 0
    assert capsys.readouterr().out == f"wrote {path}: python-script 1.0.0\n"
    first = path.read_text(encoding="utf-8")
    assert templates.main(arguments) == 2
    assert "exists; a scaffold writes new files only" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == first
    for name, says, error in (("Bad", "Echo.", "no name for a scaffolded file"),
                              ("ok", "Echo `x`.", "--says is the one line"),
                              ("ok", "  ", "--says is the one line")):
        with pytest.raises(templates.TemplateError, match=error):
            code_templates.scaffold(CATALOG["python-script"], tmp_path / "x.py", says, name)
    with pytest.raises(templates.TemplateError, match="only a code template scaffolds"):
        code_templates.scaffold(CATALOG["work"], tmp_path / "x.md", "Echo.")
    with pytest.raises(templates.TemplateError, match="is a code template and has no fields to fill; its "
                                                      "scaffold writes the file"):
        templates.fill(CATALOG["python-script"], {}, "raw")


CODE_NOTE = """---
name: thing
version: 1.0.0
kind: code
reader: fleet
says: "A thing."
tags: ["code"]
applies:
  actions: ["file.write"]
  paths: ["things/*.txt"]
adapter:
  lines:
    - pattern: "# thing"
      says: "the marker"
---

{body}"""


@pytest.mark.parametrize(("body", "error"), [
    ("Text.\n", "a code template's body holds only `## <path>` headings"),
    ("## a.txt\n\nNo fence.\n", "the file a.txt has no fenced block under its heading"),
    ("## a.txt\n\n```\n# thing\n", "the fenced block of a.txt is never closed"),
    ("", "a code template's body holds the files it scaffolds"),
    ("## a.txt\n\n```\nx\n```\n\n## a.txt\n\n```\ny\n```\n", "names each file once; it names a.txt twice"),
    ("## a.txt\n\n```\n{{nope}}\n```\n", r"\{\{nope\}\} in a.txt is no placeholder"),
])
def test_a_code_template_whose_body_is_not_its_files_does_not_load(body, error):
    with pytest.raises(templates.TemplateError, match=error):
        templates._loaded([(templates.PROJECT_REPOSITORY, {"thing.md": CODE_NOTE.format(body=body)},
                            lambda file: f"templates/{file}")])
    with_fields = CODE_NOTE.format(body="## a.txt\n\n```\n# thing\n```\n").replace(
        "tags:", 'fields: [{"name": "x", "kind": "line"}]\ntags:')
    with pytest.raises(templates.TemplateError, match="a code template has no fields"):
        templates._loaded([(templates.PROJECT_REPOSITORY, {"thing.md": with_fields},
                            lambda file: f"templates/{file}")])


def test_a_code_template_keeps_a_longer_fence_and_its_inner_fences(tmp_path):
    body = "## {{name}}.txt\n\n````text\n# thing\n```\ninner\n```\n{{says}}\n````\n"
    [template] = templates._loaded([(templates.PROJECT_REPOSITORY, {"thing.md": CODE_NOTE.format(body=body)},
                                     lambda file: f"templates/{file}")]).values()
    assert code_templates.scaffold(template, tmp_path / "probe.txt", "Says it.") == {
        tmp_path / "probe.txt": "# thing\n```\ninner\n```\nSays it.\n"}


def gate(capsys, monkeypatch, root: Path, tool: str, **given) -> str:
    text = json.dumps({"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(root),
                       "tool_name": tool, "tool_input": given})
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    assert se_templates.main(["gate", "--templates", str(ROOT / "templates"), "--root", str(root)]) == 0
    return capsys.readouterr().out


def test_a_plain_write_of_a_new_script_is_refused_naming_the_scaffold_and_the_scaffolded_one_passes(
        capsys, monkeypatch, tmp_path):
    """Acceptance 4 and requirement 6: a Write of scripts/new_thing.py that is no scaffold is denied,
    naming both scaffold calls; the scaffolded file, and an edit that keeps its shape, pass; an
    edit that drops its shape is denied naming the line."""
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    path = root / "scripts" / "new_thing.py"
    denied = json.loads(gate(capsys, monkeypatch, root, "Write", file_path=str(path),
                             content="#!/usr/bin/env python3\nprint('hi')\n"))["hookSpecificOutput"]
    assert denied["permissionDecision"] == "deny"
    reason = denied["permissionDecisionReason"]
    for name in ("python-module", "python-script"):
        assert (f"  scripts/new_thing.py: its scaffold ({name}): uv run python "
                f"{ROOT / 'scripts' / 'templates.py'} scaffold {name} --path {path} --says <one line> "
                f"--root {root}") in reason
    assert reason.endswith("or scaffold a new file: the scaffold writes it with its marker and shape, its "
                           "slots for the rest, and an edit that keeps them passes")
    [text] = scaffolded("python-script", path).values()
    assert gate(capsys, monkeypatch, root, "Write", file_path=str(path), content=text) == ""
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    assert gate(capsys, monkeypatch, root, "Edit", file_path=str(path), old_string="print(\" \".join(options.words))",
                new_string="print(len(options.words))") == ""
    dropped = gate(capsys, monkeypatch, root, "Edit", file_path=str(path),
                   old_string="raise SystemExit(se_script.run(main))", new_string="main()")
    assert "the entry: the `__main__` block ends" in json.loads(dropped)["hookSpecificOutput"][
        "permissionDecisionReason"]


def test_the_gate_s_owned_globs_name_the_code_templates_claims():
    """SE's start hands se_hook.sh every owned glob; the code templates' are among them."""
    owned = templates.owned(CATALOG)
    for glob, name in (("scripts/*.py", "python-script"), ("scripts/*.py", "python-module"), ("go.mod", "go-module"),
                       ("**/go.mod", "go-module"), (".se/components/*/__init__.py", "python-component")):
        assert (glob, name) in owned
    assert se_templates.claims_a_carried_path(CATALOG)


def test_se_component_add_renders_its_files_through_the_python_component_template(tmp_path):
    """Requirement 4 and acceptance 3: the generator that emits code, `se component add`, writes what
    the code template scaffolds, its marker first."""
    se_component.add(tmp_path, "my-probe")
    folder = tmp_path / ".se" / "components" / "my-probe"
    made = code_templates.scaffold(CATALOG["python-component"], se_component.COMPONENTS / "my-probe",
                              "An ad hoc component: say what my-probe does.", "my-probe")
    assert {path.name: text for path, text in made.items()} == {
        name: (folder / name).read_text(encoding="utf-8") for name in ("component.toml", "__init__.py")}
    init = (folder / "__init__.py").read_text(encoding="utf-8")
    assert init.startswith("# se:template se/python-component 1.0.0\n") and "my_probe = component(\"my-probe\")" in init
    assert findings(init, ".se/components/my-probe/__init__.py") == []


def test_se_script_s_parser_adds_the_logging_help_after_the_epilog_and_its_level_reads_the_variable():
    assert se_script.parser(prog="x").epilog == se_script.LOG_HELP
    assert se_script.parser(prog="x", epilog="More.").epilog == f"More.\n\n{se_script.LOG_HELP}"
    assert se_script.level({}) == logging.WARNING
    assert se_script.level({"SE_LOG_LEVEL": " info "}) == logging.INFO
    assert se_script.level({"SE_LOG_LEVEL": "loud"}) == logging.WARNING


def test_se_script_run_configures_logging_once_and_answers_the_exit_code(capsys, monkeypatch):
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    monkeypatch.setattr(sys, "argv", ["probe.py"])
    try:
        assert se_script.run(lambda: None, {}) == 0
        assert se_script.run(lambda: 3, {}) == 3
        assert sum(handler.get_name() == "se_script" for handler in root.handlers) == 1
        with pytest.raises(SystemExit):
            se_script.run(lambda: sys.exit(4), {})
        with pytest.raises(ValueError):
            se_script.run(lambda: int("x"), {})
    finally:
        root.handlers[:], root.level = handlers, level
    assert capsys.readouterr().err == ""


def test_se_script_imports_the_standard_library_only():
    """The scripts that may import nothing but the standard library (story_check.py, cold_run.py)
    may import se_script, because it imports nothing else."""
    import ast

    tree = ast.parse(Path(se_script.__file__).read_text(encoding="utf-8"))
    modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names}
    modules |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert modules <= set(sys.stdlib_module_names) | {"__future__"}, modules


def test_stop_check_and_push_check_nothing_where_the_integration_branch_shares_no_merge_base(tmp_path):
    """SE's code templates claim carried paths in every project, so stop-check and push read the
    changes; a checkout with no origin/<integration branch> to compare with yet passes, and CI's
    check job holds its pull request to its base."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "free.py").write_text("print(1)\n", encoding="utf-8")
    assert se_templates.claims_a_carried_path(se_templates.claim_templates(tmp_path, None)[0])
    assert se_templates.changed_refusal(tmp_path, "origin/main") is None
