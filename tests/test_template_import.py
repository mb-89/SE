"""Import adapters (scripts/template_import.py, docs/templates.md "Template repositories"): the
declaration, the interface (changed, then the note, then the overlay), the Markdown adapter, and a
changed source reaching the fill with its overlay applied."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import template_import
import templates
from test_templates import commit_all, synced, template_project, template_repository

#: A Markdown template note as a source tool keeps it: front matter, a page title, sections with
#: comment instructions in both kinds, placeholders, a fenced heading and a section without one.
SOURCE = """---
tags: [obsidian]
---
# {{title}}

Intro text the import leaves out.

## Attendees
<!-- Who was there,
one per line. -->
- 

## Decisions
%% What was decided. %%
<!-- With who decided it. -->
### Details
```md
## Not a section
```

## Next steps
"""

DECLARED = """imports:
  - name: meeting
    adapter: markdown
    source: vault/Meeting.md
    version: {version}
    kind: document
    reader: owner
    says: "A meeting note."
    tags: ["meeting"]
    applies: {{"actions": ["issue.create"]}}
"""

#: The overlay the repository keeps beside the imported note: it tightens and adds.
OVERLAY = """---
extends: meeting
tags: ["decisions"]
rules:
  required: refuse
fields:
  - name: decisions
    required: true
  - name: owner
    kind: line
    required: true
---

## Next steps

<!-- next_steps: Each step with its owner. -->

## Owner

<!-- owner: Who keeps the note. -->
"""


def repository(root: Path, source: str = SOURCE, version: str = "1.0.0", overlay: str = OVERLAY) -> Path:
    """`root` as a template repository importing `meeting` from its vault; its templates/."""
    (root / "vault").mkdir(parents=True, exist_ok=True)
    (root / "vault" / "Meeting.md").write_text(source, encoding="utf-8")
    folder = root / "templates"
    folder.mkdir(exist_ok=True)
    (folder / "imports.yaml").write_text(DECLARED.format(version=version), encoding="utf-8")
    if overlay:
        (folder / "meeting.overlay.md").write_text(overlay, encoding="utf-8")
    return folder


def test_the_markdown_adapter_makes_headings_sections_and_comments_instructions(tmp_path):
    folder = repository(tmp_path, overlay="")
    assert template_import.refresh(folder) == ["imported meeting from vault/Meeting.md (markdown)"]
    note = (folder / "meeting.md").read_text(encoding="utf-8")
    assert "Intro text" not in note and "Not a section" not in note and "Details" not in note
    assert note.endswith("## Attendees\n\n<!-- attendees: Who was there, one per line. -->\n\n"
                         "## Decisions\n\n<!-- decisions: What was decided. With who decided it. -->\n\n"
                         "## Next steps\n\n<!-- next_steps: -->\n")
    meeting = templates.load(tmp_path, folder=folder)["meeting"]
    assert [(item.name, item.kind, item.heading) for item in meeting.fields] == [
        ("attendees", "text", "Attendees"), ("decisions", "text", "Decisions"),
        ("next_steps", "text", "Next steps")]
    assert (meeting.version, meeting.tags, meeting.says, meeting.actions) == (
        "1.0.0", ("meeting",), "A meeting note.", ("issue.create",))
    assert meeting.field("next_steps").says == ""  # a heading alone: its overlay supplies it


def test_the_adapter_says_changed_only_where_the_source_or_its_declaration_changed(tmp_path):
    folder = repository(tmp_path)
    adapter = template_import.ADAPTERS["markdown"]
    entry, = template_import.imports(folder)
    assert adapter.changed(entry, None)
    template_import.refresh(folder)
    written = (folder / "meeting.md").read_text(encoding="utf-8")
    assert not adapter.changed(entry, written) and template_import.refresh(folder) == []
    (tmp_path / "vault" / "Meeting.md").write_text(SOURCE + "\n## Risks\n", encoding="utf-8")
    assert adapter.changed(entry, written)
    repository(tmp_path, version="1.1.0")
    entry, = template_import.imports(folder)
    assert adapter.changed(entry, written)
    assert template_import.refresh(folder) == ["imported meeting from vault/Meeting.md (markdown)"]
    assert 'version: "1.1.0"' in (folder / "meeting.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("change, refusal", [
    (lambda text: text.replace("    adapter: markdown\n", ""), "import 1: give adapter"),
    (lambda text: text.replace("markdown", "notion"), "adapter 'notion' is none of markdown"),
    (lambda text: text.replace("vault/Meeting.md", "/abs/Meeting.md"), "relative to the folder above templates/"),
    (lambda text: text.replace("vault/Meeting.md", "../Meeting.md"), "stays inside it"),
    (lambda text: text.replace("vault/Meeting.md", "vault/Missing.md"), "source vault/Missing.md cannot be read"),
    (lambda text: text + "    owner: alice\n", "owner is no key of an import"),
    (lambda text: text + text.removeprefix("imports:\n"), "imports meeting a second time"),
    (lambda text: text.replace("kind: document", "kind: interface"), "kind interface has no sections"),
])
def test_a_wrong_declaration_refuses_naming_the_entry_and_writes_nothing(tmp_path, change, refusal):
    folder = repository(tmp_path)
    path = folder / "imports.yaml"
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(templates.TemplateError, match=re.escape(refusal)):
        template_import.refresh(folder)
    assert not (folder / "meeting.md").exists()


@pytest.mark.parametrize("source, refusal", [
    ("# Title\n\nNo sections.\n", "no `##` heading"),
    ("## Notes\n\n## notes\n", "heading 'notes' is field notes again, as line 1"),
    ("## ???\n", "heading '???' names no field"),
])
def test_a_source_without_its_sections_refuses(tmp_path, source, refusal):
    folder = repository(tmp_path, source=source, overlay="")
    with pytest.raises(templates.TemplateError, match=re.escape(refusal)):
        template_import.refresh(folder)


def test_refresh_command_names_what_it_wrote(tmp_path, capsys):
    folder = repository(tmp_path)
    assert template_import.main(["refresh", "--templates", str(folder)]) == 0
    assert capsys.readouterr().out == "imported meeting from vault/Meeting.md (markdown)\n"
    assert template_import.main(["refresh", "--templates", str(folder)]) == 0
    assert capsys.readouterr().out == ""


# Acceptance: a changed source template reaches the fill with its overlay applied; a loosening
# overlay is refused.

FIELDS = {"attendees": "Alice", "decisions": "Ship the export.", "next_steps": "Alice ships it.",
          "owner": "Alice"}
RAW = "Alice came. We decided: ship the export. Alice ships it."


def fill(capsys, *where: str, fields: dict = FIELDS) -> tuple[int, str, str]:
    capsys.readouterr()
    code = templates.main(["fill", "meeting", "--input-text", RAW, "--fields-json", json.dumps(fields),
                           *where])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_a_changed_source_reaches_the_fill_with_its_overlay_applied(tmp_path, capsys, fake_git_door):
    """The project's own templates/ imports `meeting`: each fill asks the adapter first, so an edit
    in the source tool reaches the next fill, under the overlay's rules and sections."""
    project = tmp_path / "project"
    repository(project)
    code, out, err = fill(capsys, "--root", str(project))
    assert code == 0, out + err
    assert err == "imported meeting from vault/Meeting.md (markdown)\n"
    assert "## Owner\n\nAlice" in out and "## Risks" not in out
    (project / "vault" / "Meeting.md").write_text(
        SOURCE + "## Risks\n<!-- What could go wrong. -->\n", encoding="utf-8")
    code, out, err = fill(capsys, "--root", str(project), fields={**FIELDS, "risks": "None seen."})
    assert code == 0, out + err
    assert err == "imported meeting from vault/Meeting.md (markdown)\n"
    meeting = templates.catalog(project, tree=True)["meeting"]
    assert meeting.marker_line in out
    assert "## Risks\n\nNone seen." in out and "## Owner\n\nAlice" in out
    assert meeting.field("risks").says == "What could go wrong."
    assert meeting.tags == ("meeting", "decisions")
    # The overlay's tightening holds on the refreshed template: the field it made required refuses.
    code, out, _ = fill(capsys, "--root", str(project), fields={**FIELDS, "decisions": ""})
    assert code == 1 and "decisions [required]" in out and "nothing was written" in out


def test_a_template_repository_s_import_is_refreshed_before_the_fill(tmp_path, capsys, fake_git_door,
                                                                      monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nowhere")
    upstream = tmp_path / "upstream" / "shared"
    template_repository(upstream, {})
    repository(upstream)
    template_import.refresh(upstream / "templates")
    commit_all(upstream)
    import git_door
    ref = git_door.run("-C", str(upstream), "rev-parse", "HEAD").stdout.strip()
    project, local = template_project(tmp_path, {"shared": ref}, ["shared"])
    synced(project, local, capsys)
    placed = project / ".se" / "modules" / "shared"
    (placed / "vault" / "Meeting.md").write_text(SOURCE + "## Risks\n", encoding="utf-8")
    code, out, err = fill(capsys, "--root", str(project), fields={**FIELDS, "risks": "None."})
    assert code == 0, out + err
    assert err == "imported meeting from vault/Meeting.md (markdown)\n"
    assert "<!-- se:template shared/meeting 1.0.0 sha256:" in out and "## Risks\n\nNone." in out


def test_a_loosening_overlay_refuses_the_fill_and_writes_nothing(tmp_path, capsys):
    project = tmp_path / "project"
    repository(project, overlay="---\nextends: meeting\nfields:\n  - name: decisions\n    kind: line\n---\n")
    target = tmp_path / "out.md"
    code, out, err = fill(capsys, "--root", str(project), "--out", str(target))
    assert code == 2 and out == "" and not target.exists()
    assert "the overlay loosens meeting: field decisions: kind changes from 'text' to 'line'" in err
