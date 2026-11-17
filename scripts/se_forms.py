#!/usr/bin/env python3
"""SE's side of forms: the forms engine (`forms.py`) with the checks SE's filing commands add, as
the command component `forms` that kern's MCP door serves as its tool `forms` (README "Forms").

The engine stays free of SE's own scripts; this script joins it to them. Its three commands only
read: nothing is filed, written or sent through them, and none calls GitHub or starts a model.

- `se_forms.py list [--tree]` prints what `forms.py list` prints: every form of SE's with its
  actions and, for an adapter, its checker.
- `se_forms.py draft <form> [--markdown] [--tree]` prints the JSON `forms.py draft --json` prints:
  `form`, `says`, `fields`, `field_says`, `field_shape` and `schema`; `--markdown` the Markdown
  draft `forms.py draft` prints. An unknown form is answered with the list of forms, exit code 2.
- `se_forms.py check` takes what `forms.py check` takes: a form, or `--action` with `--repo`,
  `--labels` and `--base` to select one as a write would; the text as one of `--body`,
  `--body-file`, `--fields` and `--fields-json`; `--title`; `--render`; `--tree`. Besides,
  `--worktree` names the project whose local list of private terms is read (default: the
  directory it runs in). It checks the text and the title as a filing command would file them
  (`forms.formed` with `[forms] enforce = "refuse"`, a fields object always rendered):
  - the form's own check (`forms.check`, through `work_tickets.form_findings`, or
    `forms.select`'s refused markers with `--action`);
  - the private terms of `forms.private_findings` for the project's root, as
    `work_tickets.form_findings` runs them: a finding names the field and the list, never the term;
  - the name rule, `work_tickets.name_refusal` (what `checked_name` refuses), where the form's
    title field takes `work_tickets:name_refusal` as its shape (`ticket`, `work`) and a title is
    given; it replaces the form's own warning of that shape;
  - for a form of an issue, the SE commands that do not exist, as `work_tickets.refuse_dangling`
    finds them, where the form's own check named none.

**Its answer.** `check` exits 0 whatever it finds, and 2 on a usage error only, as kern's door
answers any other exit code as `command-failed` with a remedy about usage. Its first line is the
verdict, `passes` or `refused: <n> findings` (n the refused ones). A refusal goes on with every
finding as `forms.report` writes it, at most REFUSAL_LINES lines, ending with the line that names
`se_forms.py draft <form>`. A pass goes on with its warnings, one a line, or with `--render` with
the Markdown to file (the warnings then on stderr). Where no form applies to `--action`, it passes
and says `free: no form applies (<action>)` (on stderr with `--render`, the text as given after).

Standard library only; it imports `forms` and `work_tickets` as the scripts beside it."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: The title shape of the forms whose title is a ticket's name (forms/ticket.toml, forms/work.toml).
NAME_SHAPE = "work_tickets:name_refusal"
NAME_RULE = "name"
DANGLING_RULE = "dangling"
COMMAND = "se_forms.py check"
PASSES = "passes"


def sibling(name: str):
    """The script `<name>.py` beside this one, imported when a command needs it."""
    here = str(HERE)
    if here not in sys.path:
        sys.path.append(here)
    return importlib.import_module(name)


#: se_forms.py's commands as one kern component (README "Commands as components"); each command's
#: usage and help come from make_parser.
COMPONENTS = (sibling("se_components").Group(
    "forms", "Forms",
    "SE's forms: list names them, draft gives a form's fields, their instructions and their shape, "
    "and check finds everything SE's filing commands would refuse in a text, or gives the Markdown "
    "to file.",
    ("list", "draft", "check")),)
#: The commands that go through kern where it runs (se_components.routed): all three only read.
INTERACTIVE_COMMANDS = frozenset({"list", "draft", "check"})
#: The commands that change nothing, each with when an agent uses it: kern's MCP door offers them.
READ_ONLY_COMMANDS = {
    "list": "Lists SE's forms with the actions each shapes. Use it to find the form for a text "
            "before writing it.",
    "draft": "Gives a form's fields, what belongs in each (field_says), their shape and a JSON "
             "Schema of them. Use it before writing an issue, a pull request or a report SE "
             "checks.",
    "check": "Checks a text or a fields object against a form as SE's filing commands would: its "
             "first line is passes or refused, then every finding or, with --render, the Markdown "
             "to file. Use it before filing; it files nothing.",
}


def make_parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="se_forms.py", description=__doc__.splitlines()[0])
    commands = top.add_subparsers(dest="command", required=True)
    tree = {"action": "store_true", "help": "read the working tree's forms/ (default: forms/ at "
                                            "origin/<integration branch> where it holds them)"}
    listing = commands.add_parser("list", help="name every form with its actions")
    listing.add_argument("--tree", **tree)
    drafting = commands.add_parser(
        "draft", help="print a form's fields, their instructions, their shape and its schema",
        description="Print the JSON forms.py draft --json prints; --markdown the empty form.")
    drafting.add_argument("form", help="the form, as list names it")
    drafting.add_argument("--markdown", action="store_true", help="print the Markdown draft")
    drafting.add_argument("--tree", **tree)
    checking = commands.add_parser(
        "check", help="check a text against a form as SE's filing commands would",
        description="Check a body or a fields object as a filing command would file it: the "
                    "form's check, the private terms, the name rule and SE's commands. It exits "
                    "0; its first line is passes or refused: <n> findings.")
    checking.add_argument("form", nargs="?", help="the form; without it, --action selects one")
    given = checking.add_mutually_exclusive_group(required=True)
    given.add_argument("--body-file", type=Path, help="the body as a file")
    given.add_argument("--fields", type=Path, help="the field values as a JSON file")
    given.add_argument("--body", help="the body as text")
    given.add_argument("--fields-json", help="the field values as JSON text, as --fields holds")
    checking.add_argument("--title", help="the title it would be filed with")
    checking.add_argument("--render", action="store_true",
                          help="where it passes, the Markdown to file after the first line")
    checking.add_argument("--action", choices=sibling("forms").ACTIONS, metavar="ACTION",
                          help="select the form as a write of this action would: one of "
                               + ", ".join(sibling("forms").ACTIONS))
    checking.add_argument("--repo", help="with --action: the repository written to")
    checking.add_argument("--labels", help="with --action: the labels, comma-separated")
    checking.add_argument("--base", help="with --action: a pull request's base branch")
    checking.add_argument("--worktree", type=Path, default=Path("."),
                          help="the project whose private terms are checked (default: .)")
    checking.add_argument("--tree", **tree)
    for command in (listing, drafting, checking):
        command.set_defaults(run={"list": run_list, "draft": run_draft,
                                  "check": run_check}[command.prog.split()[-1]])
    return top


class Usage(Exception):
    """A usage error: its message is the answer, exit code 2."""


def loaded(options: argparse.Namespace) -> dict:
    forms = sibling("forms")
    try:
        return forms.load(forms.ROOT, tree=options.tree)
    except forms.FormError as error:
        raise Usage(str(error)) from error


def named(forms_by_name: dict, name: str, command: str):
    """The form `name`, or a Usage error answering with the list of forms."""
    if name not in forms_by_name:
        raise Usage("\n".join([f"{command}: no form {name!r}; the forms are:",
                               *sibling("forms").list_forms(forms_by_name)]))
    return forms_by_name[name]


def run_list(options: argparse.Namespace) -> int:
    print("\n".join(sibling("forms").list_forms(loaded(options))))
    return 0


def run_draft(options: argparse.Namespace) -> int:
    forms = sibling("forms")
    form = named(loaded(options), options.form, "se_forms.py draft")
    if options.markdown:
        print(forms.draft(form), end="")
    else:
        print(json.dumps(forms.draft_fields(form), indent=2))
    return 0


def given_text(options: argparse.Namespace) -> tuple[str | None, dict | None]:
    """The body or the field values `check` was given, by whichever of its four options."""
    forms = sibling("forms")
    try:
        if options.body is not None:
            return options.body, None
        if options.body_file is not None:
            try:
                return options.body_file.read_text(encoding="utf-8"), None
            except OSError as error:
                raise Usage(f"{COMMAND}: cannot read --body-file {options.body_file} "
                            f"({error})") from error
        if options.fields_json is not None:
            return None, forms.fields_data(options.fields_json, "--fields-json", COMMAND)
        return None, forms.fields_file(options.fields, COMMAND)
    except forms.FormError as error:
        raise Usage(str(error)) from error


def filed(form, body: str | None, values: dict | None, title: str | None) -> tuple[str, str | None]:
    """The body and the title as a filing command files them: fields rendered through the form,
    a body parsed and rendered again as with `[forms] enforce = "refuse"`."""
    forms = sibling("forms")
    if values is None:
        return forms.formed(form, body=body, enforce=forms.REFUSE), title
    values = forms.answer(form, values)
    title_field = next((item.name for item in form.fields if item.source == "title"), None)
    if title_field:
        if title is not None:
            values[title_field] = title
        elif isinstance(values.get(title_field), str):
            title = values[title_field]
    return forms.render(form, values), title


def chosen(forms_by_name: dict, options: argparse.Namespace, body: str):
    """The form `check` checks against (None: free) and the refused markers selection met."""
    forms = sibling("forms")
    if options.form is None and options.action is None:
        raise Usage(f"{COMMAND}: name a form, or give --action to select one as a write would")
    if options.form is not None and options.action is not None:
        raise Usage(f"{COMMAND}: give a form or --action, not both")
    if options.action is None and any(value is not None for value in
                                      (options.repo, options.labels, options.base)):
        raise Usage(f"{COMMAND}: --repo, --labels and --base select a form; give them with "
                    "--action")
    if options.form is not None:
        return named(forms_by_name, options.form, COMMAND), ()
    work_tickets = sibling("work_tickets")
    labels = [label.strip() for label in (options.labels or "").split(",") if label.strip()]
    try:
        where: dict[str, object] = {"labels": labels, "base": options.base,
                                    "integration": work_tickets.integration_branch(forms.ROOT)}
        if options.repo is not None:
            where.update(repo=options.repo, home=forms.home_repositories(forms.ROOT))
        selection = forms.select(forms_by_name, options.action, body, options.title, **where)
    except (forms.FormError, work_tickets.QueueError) as error:
        raise Usage(str(error)) from error
    return selection.form, selection.findings


def repository(root: Path, given: str | None) -> str:
    """The repository the text would be filed in: `--repo`, else the project's tracker or origin;
    empty where it has neither, so a bare `scripts/…` path counts as no script of SE's."""
    work_tickets = sibling("work_tickets")
    try:
        return work_tickets.resolve_repo(root, given)
    except work_tickets.QueueError:
        return ""


def findings(form, root: Path, repo: str, title: str | None, body: str) -> list:
    """Every finding a filing command would refuse or warn of for `title` and `body`."""
    forms, work_tickets = sibling("forms"), sibling("work_tickets")
    try:
        _, found = work_tickets.form_findings(root, repo, form, title or "", body)
    except work_tickets.QueueError as error:
        raise Usage(str(error)) from error
    title_field = next((item for item in form.fields if item.source == "title"), None)
    if title is None:  # no title given: the body alone is checked
        found = [item for item in found if title_field is None or item.field != title_field.name]
    elif title_field is not None and title_field.shape == NAME_SHAPE:
        refusal = work_tickets.name_refusal(title)
        if refusal:
            found = [item for item in found if not (item.field == title_field.name
                                                    and item.fix == refusal)]
            found.insert(0, forms.Finding(title_field.name, NAME_RULE, forms.REFUSE, refusal))
    if set(form.actions) & set(forms.ISSUE_ACTIONS) and not any(
            item.rule == DANGLING_RULE for item in found):
        try:
            work_tickets.refuse_dangling(repo, COMMAND, body)
        except work_tickets.QueueError as error:
            found += [forms.Finding("body", DANGLING_RULE, forms.REFUSE,
                                    f"{line.strip()}: correct it, or say in Requirements that "
                                    "this issue adds it")
                      for line in str(error).splitlines()[1:] if line.strip()]
    return sorted(found, key=lambda item: item.severity != forms.REFUSE)


def refusal(form, found: list) -> list[str]:
    """`forms.report`'s refusal, its last line naming this script's draft."""
    forms = sibling("forms")
    if form is None:
        return [f"  {item.field}: {item.fix}" for item in found if item.severity == forms.REFUSE]
    lines = forms.report(COMMAND, form, found, refused=True).splitlines()
    lines[-1] = f"The empty form: uv run python {HERE / 'se_forms.py'} draft {form.name}"
    return lines


def run_check(options: argparse.Namespace) -> int:
    forms = sibling("forms")
    forms_by_name = loaded(options)
    body, values = given_text(options)
    form, met = chosen(forms_by_name, options, body or "")
    found = list(met)
    title = options.title
    if form is None:
        rendered = body if body is not None else json.dumps(values)
    else:
        try:
            rendered, title = filed(form, body, values, title)
        except forms.FormError as error:
            raise Usage(str(error)) from error
        root = options.worktree.resolve()
        found += findings(form, root, repository(root, options.repo), title, rendered)
    refused = sum(item.severity == forms.REFUSE for item in found)
    if refused:
        print("\n".join([f"refused: {refused} findings", *refusal(form, found)]))
        return 0
    warnings = [str(item) for item in found]
    if len(warnings) > forms.REFUSAL_LINES:
        warnings = warnings[:forms.REFUSAL_LINES - 1] + [
            f"... and {len(warnings) - forms.REFUSAL_LINES + 1} more findings"]
    if form is None:
        warnings.insert(0, f"free: no form applies ({options.action})")
    if options.render:
        if warnings:
            print("\n".join(warnings), file=sys.stderr)
        print(PASSES)
        print(rendered, end="")
        return 0
    print("\n".join([PASSES, *warnings]))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    words = [args.command]
    routed = sibling("se_components").routed(
        Path(__file__), words, list(sys.argv[1 + len(words):] if argv is None else argv[len(words):]),
        args.command in INTERACTIVE_COMMANDS)
    if routed is not None:
        return routed
    try:
        return args.run(args)
    except Usage as error:
        print(error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
