---
name: fill-templates
description: 'Fill templates from raw material into a new small repository: from a plain request naming the templates, the material (a folder or a repository) and maybe a prompt, set up the repository, fill each template section by section from the material, link the notes it repeats, name each section the material cannot fill, and check every document until it passes. Use when someone asks to write, fill or draft a document from a template and some raw data, such as "write me a label spec, the template is X, my raw data is in this folder".'
---

# Fill templates

Reader: any agent SE runs, asked by anyone to turn templates and raw material into finished
documents.

The request needs three things and no more: the templates, the material and, where there is one,
a prompt. "Write me a label spec, the template is label-spec, my raw data is in `notes/`" is a whole
request. Ask only where it names no template or no material.

The templates are Markdown: a single note `<name>.md`, or a template manifest `<name>/manifest.md`
with its template nodes beside it. Written by hand or imported from any tool, they fill alike
([docs/templates.md "The template"](../../../docs/templates.md#the-template)).
[docs/templates.md "Filling templates from material"](../../../docs/templates.md#filling-templates-from-material)
holds the worked example this skill follows.

`templates.py` below is `uv run python <se>/scripts/templates.py`, run from the new repository's
root. Every call there passes `--root .`, so a name resolves in the new repository first; without
it, a name resolves in SE's own checkout.

## Steps

1. **Resolve each template.**
   - A path names the note, or the manifest's folder; take its overlay `<name>.overlay.md` beside
     it too, where there is one.
   - A name resolves in the project the person works in: `templates.py list --root <project>`
     names what resolves there, from its own `templates/`, its template repositories, then SE's.
   - A name that resolves nowhere is reported to the person with the names that do; nothing is
     filled from a guess.
2. **Create the small repository**, outside every other checkout: the folder the person names,
   else a new folder named after the documents. In it:
   - `git init`;
   - `templates/`: each template copied as it stands, with its overlay and every template it
     `extends`, never edited, as its digest is what each document records. `templates.py list
     --root .` then names each, or the error that stops it loading, which goes to the person;
   - `material/`: the material copied as it stands, hidden folders such as `.git` left out. Of a
     repository, record its origin and `git -C <material> rev-parse HEAD`;
   - `documents/`, where the documents go.
3. **Fill each template, section by section.**
   - A single note writes its document where its `applies.paths` claim one:
     `templates.py fill <template> --root . --path documents/<name>.md --input material`. A manifest's
     document goes to `--out documents/<name>.md`.
   - A single note that claims no file (`file.write`) records no `derived_from`: tell the person,
     with the two `applies` lines the worked example's `label-spec` carries, and fill it only once
     they added them.
   - First call it without fields. Its answer is the instructions: each section's guidance (a
     manifest's `contents`, `Why`, `Form` and `Sources`), the rules of honest fields and the
     guidance its tags resolve. Read them all before writing a section.
   - Write each section from the material and the prompt, judging what belongs there by its
     guidance. Then fill with the fields, `--fields-json '<object>'` or `--fields <file>`.
   - A refusal names every finding and writes nothing: fix each, and fill again.
4. **Link, never copy.** A section that repeats a note of the material links it, by a relative
   link from `documents/` to `../material/<note>.md`, and says only what the section needs from
   it.
5. **Never invent, never leave a slot.** A section the material cannot fill holds `Not in input`,
   alone; never a guess, an empty section or the fill slot `{{slot}}`.
6. **Check every document until it passes**:
   `templates.py documents --root . --path documents --input material`.
   - It checks each document against the template its `derived_from` names, and the quotes against
     the material.
   - Exit 1 names each finding: fill that document again until it exits 0.
   - Each line `<file>: <section>: not in input` (or `: empty`) is a section the material did not
     fill.
7. **Write the README**, the repository's front page:
   - each document with its template and version, as its `derived_from` records them;
   - the material: where it came from, and for a repository its origin and commit;
   - the prompt as it was given, or "none";
   - each section the material did not fill, by its document and heading.
8. **Commit** the repository, then report to the person: the repository's path, each document, and
   each section the material did not fill, by name. Report done only once step 6 exits 0.
