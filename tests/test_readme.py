"""The one-page README (scripts/readme.py, the guidance note readme-is-one-page, SE#1796): each rule
fails on a README that breaks it and passes one that keeps it; the showcase command is the README's
own, with CI's clone address and branch. Files only: no git, no network, no process."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import readme  # noqa: E402

COMMAND = "git clone https://github.com/<owner>/<repository> tool && cd tool && ./RUNME.sh demo"
GOOD = f"""# tool

```sh
{COMMAND}
```

That line installs the tool and runs its demo. The [full documentation](docs.md) holds the rest.

## What it is

Tool makes a hard job one command. It is for people who do the job by hand today.

## Read on

- [Install](docs/install.md)
"""


def test_a_one_page_readme_with_its_command_first_passes() -> None:
    assert readme.findings(GOOD) == []


def test_a_readme_over_sixty_lines_fails() -> None:
    long = GOOD + "\n".join(f"- [Page {n}](docs/{n}.md)" for n in range(50)) + "\n"
    assert any(finding.startswith(f"{len(long.splitlines())} lines; a README holds at most 60")
               for finding in readme.findings(long))


def test_a_readme_over_3500_characters_fails_headings_included() -> None:
    heavy = GOOD.replace("## What it is", "## " + "What it is, at length " * 160)
    assert len(heavy.splitlines()) <= readme.MAX_LINES
    assert any(f"{len(heavy)} characters; a README holds at most 3500" in finding
               for finding in readme.findings(heavy))


@pytest.mark.parametrize("text", [
    GOOD.replace(f"```sh\n{COMMAND}\n```\n", ""),
    GOOD.replace(f"{COMMAND}\n", f"{COMMAND}\n./RUNME.sh more\n"),
    "\n" * 9 + GOOD,
], ids=["no block", "two commands", "below line 10"])
def test_the_one_command_must_open_the_readme(text: str) -> None:
    assert "no code block of one command within its first 10 lines: open with the one command that " \
           "gets, installs and runs the showcase" in readme.findings(text)


def test_a_comment_in_the_block_is_no_second_command() -> None:
    assert readme.findings(GOOD.replace(f"{COMMAND}\n", f"# get, install, run\n{COMMAND}\n")) == []


def test_the_documentation_link_must_open_the_readme_too() -> None:
    text = GOOD.replace("The [full documentation](docs.md) holds the rest.", "Read docs.md.")
    assert readme.findings(text) == [
        "no link to the full documentation within its first 10 lines: a link whose text names the "
        "documentation"]


def test_what_it_is_takes_at_most_five_sentences() -> None:
    pitch = "It does one thing. " * 6
    found = readme.findings(GOOD.replace("Tool makes a hard job one command.", pitch.strip()))
    assert found == ["7 sentences say what it is; at most 5: keep the pitch, move feature, command "
                     "and mechanism detail to the documentation"]


def test_code_spans_and_link_targets_end_no_sentence() -> None:
    assert readme.sentences("Run `a.py check. now` from [the docs](docs/a.md). Then stop") == 2


def test_a_readme_without_a_pitch_or_without_links_fails() -> None:
    bare = GOOD.split("## What it is")[0] + "## Read on\n\n- [Install](docs/install.md)\n"
    assert readme.findings(bare) == [
        "no description after the opening: say what it is, who it is for and its big value "
        "propositions in at most 5 sentences"]
    unlinked = GOOD.split("## Read on")[0]
    assert readme.findings(unlinked) == ["no list of links after the description: link the rest"]


def test_the_showcase_is_the_readmes_command_with_cis_address_and_branch() -> None:
    assert readme.showcase(GOOD) == COMMAND
    assert readme.showcase(GOOD, "https://example.com/o/tool", "work") == (
        "git clone --branch work https://example.com/o/tool tool && cd tool && ./RUNME.sh demo")
    assert readme.showcase("# tool\n") is None


def test_main_checks_and_prints_the_showcase(tmp_path: Path, capsys) -> None:
    assert readme.main(["check", "--root", str(tmp_path)]) == 2
    assert "no README.md in" in capsys.readouterr().err
    (tmp_path / "README.md").write_text(GOOD, encoding="utf-8")
    assert readme.main(["check", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "README.md: one page, its command first\n"
    assert readme.main(["showcase", "--root", str(tmp_path), "--branch", "b"]) == 0
    assert capsys.readouterr().out == COMMAND.replace("git clone", "git clone --branch b") + "\n"
    (tmp_path / "README.md").write_text("# tool\n", encoding="utf-8")
    assert readme.main(["check", "--root", str(tmp_path)]) == 1
    assert "README.md: no code block of one command" in capsys.readouterr().out
    assert readme.main(["showcase", "--root", str(tmp_path)]) == 1


def test_ses_own_readme_passes_and_its_showcase_runs_runme() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.findings(text) == []
    command = readme.showcase(text, "https://example.com/o/se", "work")
    assert command.startswith("git clone --branch work https://example.com/o/se se && cd se && ./RUNME.sh ")

