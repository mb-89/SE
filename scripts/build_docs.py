"""Build se's documentation, one HTML file, from `docs.md` with the obs module.

The README section "Documentation" owns what this builds and where it is published. Exit code 0:
built without a warning; 1: the build failed or obs warned (each warning is printed); 2: setup error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

import rule_book

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs.md"
MODULES = ROOT / "scripts" / "se_modules.py"
# The rule book's place in the manifest's folder; the build shows it as one table of its rules.
BOOK = Path("src", "skills", "work-model", "references", "rules.md")
# obs's core configuration for this build. Its lints run at obs's defaults; every obs warning,
# long paragraphs, broken links and missing notes included, fails the build.
CORE_CONFIG = {
    "input": {"manifestFilename": MANIFEST.name, "projectConfigFilename": "cfg.json"},
    "execution": {"commandTimeoutSeconds": 15},
}


# The obs module's directory, already at its pin: obs_dir returns it without syncing again (the
# suite's `obs` fixture sets it once it has synced, so a test's builds run no git).
OBS_VARIABLE = "SE_OBS_DIR"


def obs_dir() -> Path:
    """Bring the obs module to its pin in se.toml and return the directory it is used from."""
    if os.environ.get(OBS_VARIABLE):
        return Path(os.environ[OBS_VARIABLE])
    for command in ("sync", "path"):
        result = subprocess.run([sys.executable, str(MODULES), command, "obs"], cwd=ROOT,
                                capture_output=True, text=True)
        if result.returncode:
            print(f"se_modules.py {command} obs failed:\n{result.stderr}{result.stdout}", file=sys.stderr)
            sys.exit(2)
    return Path(result.stdout.strip().splitlines()[-1])


def child_environment() -> dict[str, str]:
    """This environment without uv's deprecated UV_NATIVE_TLS and the caller's VIRTUAL_ENV, whose notices
    would read as warnings (obs runs in its own project's environment)."""
    environment = dict(os.environ)
    environment.pop("VIRTUAL_ENV", None)
    if environment.pop("UV_NATIVE_TLS", None):
        environment.setdefault("UV_SYSTEM_CERTS", "1")
    return environment


#: obs's Python by obs folder, as ``obs_document_command`` read it once per process.
_PYTHON: dict[Path, str] = {}


def obs_document_command(obs: Path) -> list[str]:
    """obs-document as obs's own environment's Python runs it, that environment synced first by ``uv
    run``. Not ``uv run obs-document``: uv sets VIRTUAL_ENV for it, obs passes its environment on to
    the adapter's own ``uv run``, and uv warns there that the two environments differ."""
    if obs not in _PYTHON:
        result = subprocess.run(["uv", "run", "--quiet", "--project", str(obs), "python", "-c",
                                 "import sys; print(sys.executable)"],
                                cwd=ROOT, capture_output=True, text=True, env=child_environment())
        said = result.stdout.strip().splitlines()
        if result.returncode or not said:
            return ["uv", "run", "--quiet", "--project", str(obs), "obs-document"]  # fails as obs says
        _PYTHON[obs] = said[-1]
    return [_PYTHON[obs], "-m", "obs.document"]


#: What an obs build may print that names no note to fix, so it fails no build: obs-html cannot
#: name the commit it was installed at, as it reads it only from obs's own tree (its
#: src/obs_html/render.py `_editable_source_commit`), and SE builds from a copy without Git.
KNOWN_WARNINGS = ("generation provenance: cannot resolve the generator commit",)


def obs_warnings(output: str) -> list[str]:
    """The lines of ``output`` that warn, except those ``KNOWN_WARNINGS`` names."""
    return [line for line in output.splitlines()
            if "warning" in line.casefold() and not any(known in line for known in KNOWN_WARNINGS)]


def obs_document(obs: Path, arguments: list[str], tool: str, adapter: bool = True,
                 renamed: tuple[Path, Path] | None = None) -> int:
    """Run obs-document with ``arguments`` through the adapter component ``ADAPTER``, installed first
    where it is missing (``ready_adapter``; without it, unless ``adapter``: a parse into ``--document``
    only); 1 on a failure or any warning, and where no ``ADAPTER`` can be installed, naming
    ``ADAPTER_REMEDY``.

    Each warning is printed to stderr under ``tool``'s name; scripts/deck.py shares this run. With
    ``renamed`` (a copy's folder, its source's folder), obs's output names the source's files.
    """
    if adapter:
        found, refusal = ready_adapter(obs)
        if found is None:
            print(f"{tool}: {refusal}", file=sys.stderr)
            return 1
    result = subprocess.run(
        [*obs_document_command(obs), *(["--adapter", ADAPTER] if adapter else []), *arguments],
        cwd=ROOT, capture_output=True, text=True, env=child_environment(),
    )
    output = result.stdout + result.stderr
    if renamed:
        output = output.replace(str(renamed[0]), str(renamed[1]))
    warnings = obs_warnings(output)
    for line in warnings:
        print(line, file=sys.stderr)
    if result.returncode:
        print(f"{tool}: obs-document failed with exit code {result.returncode}:\n{output}", file=sys.stderr)
        return 1
    if warnings:
        print(f"{tool}: {len(warnings)} obs warning(s); fix the notes named above", file=sys.stderr)
        return 1
    return 0


# The adapter component every build here runs through, docs, decks and the Timeline (obs's
# spec/design_input/components.md, Choosing), and the command that installs it; obs builds with
# no other, so a build installs it where it is missing.
ADAPTER = "obs-html"
ADAPTER_REMEDY = f"obs-components install {ADAPTER}"
ADAPTER_INSTALL = tuple(ADAPTER_REMEDY.split())


def installed_adapter(obs: Path) -> tuple[dict | None, str]:
    """``ADAPTER`` as obs finds it among the machine's installed components: its manifest with the
    folder its commands run from (``folder``), and ""; or None and obs's refusal, which names
    ``ADAPTER_REMEDY``."""
    code = ("import json; from obs.adapter import adapter_location, load_adapter; "
            f"print(json.dumps({{**load_adapter({ADAPTER!r}), "
            f"'folder': str(adapter_location({ADAPTER!r}).folder)}}))")
    result = subprocess.run(["uv", "run", "--quiet", "--project", str(obs), "python", "-c", code],
                            cwd=ROOT, capture_output=True, text=True, env=child_environment())
    said = result.stdout.strip().splitlines()
    if result.returncode or not said:
        refusal = (result.stderr.strip().splitlines() or [f"exit code {result.returncode}"])[-1]
        return None, refusal
    return json.loads(said[-1]), ""


#: The adapters ``ready_adapter`` found in this process, by obs folder: a build asks obs once.
_READY: dict[Path, dict] = {}


def ready_adapter(obs: Path) -> tuple[dict | None, str]:
    """``ADAPTER`` as obs finds it, installed first (``ADAPTER_REMEDY``) where it is missing: its
    manifest with ``folder``, and ""; or None and why, naming the command and obs's refusal."""
    if obs in _READY:
        return _READY[obs], ""
    adapter, refusal = installed_adapter(obs)
    if adapter is None:
        result = subprocess.run(["uv", "run", "--quiet", "--project", str(obs), *ADAPTER_INSTALL], cwd=ROOT,
                                capture_output=True, text=True, env=child_environment())
        adapter, refusal = installed_adapter(obs)
        if adapter is None:
            said = (result.stdout + result.stderr).strip().splitlines()
            return None, (f"obs finds no adapter component {ADAPTER} ({refusal}), and `{ADAPTER_REMEDY}` "
                          f"from {obs} installed none ({said[-1] if said else f'exit code {result.returncode}'}). "
                          "Install it there, where obs's remotes reach a repository that offers it")
        print(f"build_docs: installed obs's adapter component {ADAPTER} at {adapter['folder']}", file=sys.stderr)
    _READY[obs] = adapter
    return adapter, ""


def install_html(obs: Path) -> int:
    """Install ``ADAPTER`` where it is missing (``ready_adapter``): 0 once obs finds it, saying where; 1
    where none can be installed, naming the command."""
    adapter, refusal = ready_adapter(obs)
    if adapter is None:
        print(f"build_docs: {refusal}", file=sys.stderr)
        return 1
    print(f"build_docs: obs builds with {ADAPTER} at {adapter['folder']}")
    return 0


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def build(source: Path, destination: Path, document: Path | None = None) -> int:
    """Build the manifest ``source`` into ``destination`` from a copy of its folder (``reading_copy``),
    and, with ``document``, write there the obs Document the page was built from."""
    source, destination = source.resolve(), destination.resolve()
    folder = source.parent
    if _inside(destination, folder):
        print(f"build_docs: --destination {destination} is inside the manifest's folder {folder}: the page "
              f"would become a file of the notes it is built from. Name a --destination outside {folder}.",
              file=sys.stderr)
        return 2
    obs = obs_dir()
    with tempfile.TemporaryDirectory() as scratch:
        vault = reading_copy(folder, Path(scratch) / folder.name)
        try:
            rule_table(vault)
        except FileExistsError as error:
            print(f"build_docs: {error}", file=sys.stderr)
            return 1
        if runme(vault, folder):
            return 2
        config = Path(scratch) / "obs-config.json"
        config.write_text(json.dumps(CORE_CONFIG), encoding="utf-8", newline="\n")
        written = ["--document", str(document.resolve())] if document else []
        code = obs_document(obs, ["--config", str(config), "--source", str(vault / source.name), *written,
                                  "--destination", str(destination), "--execute-commands"], "build_docs",
                            renamed=(vault, folder))
    if code == 0:
        print(f"build_docs: built {destination}")
    return code


def runme(vault: Path, folder: Path) -> int:
    """Run ``sh RUNME.sh --help`` once in the copy's root, where it holds a RUNME.sh, so what RUNME
    installs lands in the home and in the copy before obs, and the command fence's run of it there
    only hands ``--help`` on, within obs's command timeout. Its stdout is discarded, its stderr passed
    on with the copy's folder named as ``folder``; no timeout. 1 where it fails, else 0."""
    if not (vault / "RUNME.sh").is_file():
        return 0
    result = subprocess.run(["sh", "RUNME.sh", "--help"], cwd=vault, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True, env=child_environment())
    if result.stderr:
        print(result.stderr.replace(str(vault), str(folder)), end="", file=sys.stderr)
    if result.returncode:
        print(f"build_docs: sh RUNME.sh --help in the build's copy of {folder} failed with exit code "
              f"{result.returncode}; the pinned se must be in ~/.se/bin: run bash scripts/bootstrap.sh "
              "--binary in the checkout first (README \"Documentation\")", file=sys.stderr)
        return 1
    return 0


def reading_copy(folder: Path, copy: Path) -> Path:
    """Copy ``folder`` to ``copy`` as obs reads it (no dot entries, no ``__pycache__``), with no note
    asking for a verdict (``without_verdict``), and return ``copy``. Each later step of the build that
    adjusts the notes it reads adjusts this copy."""
    shutil.copytree(folder, copy, symlinks=True, ignore=shutil.ignore_patterns(".*", "__pycache__"))
    for note in copy.rglob("*.md"):
        if note.is_symlink() or not note.is_file():
            continue
        text = note.read_text(encoding="utf-8")
        changed = without_verdict(text)
        if changed != text:
            note.write_text(changed, encoding="utf-8", newline="\n")
    return copy


# A Markdown link's target: its path and its anchor.
LINK = re.compile(r"(\]\()([^)\s#]*rules\.md)#([^)\s]+)(\))")


def rule_table(vault: Path) -> None:
    """Show the copy's rule book as one table of its rules: its page and a note per rule beside it
    (``rule_book.documentation``), and every link to a rule's heading pointed at that rule's note by
    its path from the copy's root, the one form obs-html opens a note by. A vault without the book is
    left as it is; a rule note that would overwrite a file raises ``FileExistsError``, naming it."""
    book = vault / BOOK
    if not book.is_file():
        return
    shown = rule_book.documentation(book.read_text(encoding="utf-8"))
    for name in shown.notes:
        if (book.parent / name).exists():
            raise FileExistsError(f"the rule note {(BOOK.parent / name).as_posix()} would overwrite the file "
                                  "of that name beside the rule book; rename that file")
    book.write_text(shown.page, encoding="utf-8", newline="\n")
    for name, text in shown.notes.items():
        (book.parent / name).write_text(text, encoding="utf-8", newline="\n")

    def pointed(match: re.Match) -> str:
        rule = shown.anchors.get(match[3])
        if rule is None:
            return match[0]
        return f"{match[1]}{(BOOK.parent / f'{rule}.md').as_posix()}{match[4]}"

    for note in vault.rglob("*.md"):
        if note.is_symlink() or not note.is_file():
            continue
        text = note.read_text(encoding="utf-8")
        changed = LINK.sub(pointed, text)
        if changed != text:
            note.write_text(changed, encoding="utf-8", newline="\n")


def without_verdict(text: str) -> str:
    """A note's ``text`` whose frontmatter asks for no verdict: the ``bless`` key leaves its ``obs`` mapping,
    an ``obs`` mapping left empty leaves the frontmatter, and a frontmatter left empty leaves the note.

    By text, with the standard library alone (the docs workflow's ``python3`` has no YAML), as
    scripts/deck.py edits a manifest's frontmatter; everything else stays as it is."""
    lines = text.split("\n")
    if lines[0].rstrip("\r").strip() != "---":
        return text
    end = next((n for n in range(1, len(lines)) if lines[n].rstrip("\r").strip() == "---"), None)
    if end is None:
        return text
    start = next((n for n in range(1, end) if re.match(r"obs\s*:", lines[n])), None)
    if start is None:
        return text
    head, value = lines[start].split(":", 1)
    if value.strip().startswith("{"):
        entries = _flow_entries(value.strip())
        if entries is None:
            return text
        kept = [entry for entry in entries if not re.match(r"['\"]?bless['\"]?\s*:", entry)]
        if len(kept) == len(entries):
            return text
        replaced = [f"{head}: {{{', '.join(kept)}}}"] if kept else []
        lines[start:start + 1] = replaced
        end += len(replaced) - 1
    elif not value.strip():
        block = start + 1
        while block < end and (not lines[block].strip() or lines[block][:1] in (" ", "\t")):
            block += 1
        children = list(range(start + 1, block))
        bless = next((n for n in children if re.match(r"\s+['\"]?bless['\"]?\s*:", lines[n])), None)
        if bless is None:
            return text
        indent = len(lines[bless]) - len(lines[bless].lstrip())
        stop = bless + 1
        while stop < block and (not lines[stop].strip() or len(lines[stop]) - len(lines[stop].lstrip()) > indent):
            stop += 1
        del lines[bless:stop]
        block -= stop - bless
        end -= stop - bless
        if not any(lines[n].strip() for n in range(start + 1, block)):
            del lines[start:block]
            end -= block - start
    else:
        return text
    if not any(lines[n].strip() for n in range(1, end)):
        del lines[:end + 1]
    return "\n".join(lines)


def _flow_entries(value: str) -> list[str] | None:
    """The top-level entries of a YAML flow mapping ``{a: 1, b: {c: 2}}``; ``None`` where it is not one
    this reader splits (unbalanced, or text after its closing brace)."""
    depth, quote, entries, current = 0, "", [], ""
    for index, character in enumerate(value):
        if quote:
            current += character
            if character == quote:
                quote = ""
            continue
        if character in "'\"":
            quote = character
        elif character in "{[":
            depth += 1
            if depth == 1:
                continue
        elif character in "}]":
            depth -= 1
            if depth == 0:
                if value[index + 1:].strip() and not value[index + 1:].strip().startswith("#"):
                    return None
                entries.append(current.strip())
                return [entry for entry in entries if entry]
        elif character == "," and depth == 1:
            entries.append(current.strip())
            current = ""
            continue
        current += character
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=MANIFEST,
                        help="the manifest note to build (default: docs.md); its folder is the vault")
    parser.add_argument("--destination", type=Path,
                        help="the HTML file to write, outside the vault")
    parser.add_argument("--document", type=Path,
                        help="also write the obs Document the page was built from to this JSON file")
    parser.add_argument("--install-html", action="store_true",
                        help="install obs's adapter component obs-html where it is missing (obs-components install obs-html) "
                             "and stop")
    arguments = parser.parse_args(argv)
    if arguments.install_html:
        return install_html(obs_dir())
    if arguments.destination is None:
        parser.error("--destination is required, unless --install-html")
    return build(arguments.source, arguments.destination, arguments.document)


if __name__ == "__main__":
    sys.exit(main())
