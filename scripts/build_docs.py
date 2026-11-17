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

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs.md"
MODULES = ROOT / "scripts" / "se_modules.py"
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


def obs_document(obs: Path, arguments: list[str], tool: str, adapter: bool = True,
                 renamed: tuple[Path, Path] | None = None) -> int:
    """Run obs-document with ``arguments`` through the html adapter (without it, unless ``adapter``: a
    parse into ``--document`` only); 1 on a failure or any warning.

    Each warning is printed to stderr under ``tool``'s name; scripts/deck.py shares this run. With
    ``renamed`` (a copy's folder, its source's folder), obs's output names the source's files.
    """
    result = subprocess.run(
        ["uv", "run", "--quiet", "--project", str(obs), "obs-document",
         *(["--adapter", "html", "--adapter-config", str(obs / "adapters.json")] if adapter else []), *arguments],
        cwd=ROOT, capture_output=True, text=True, env=child_environment(),
    )
    output = result.stdout + result.stderr
    if renamed:
        output = output.replace(str(renamed[0]), str(renamed[1]))
    warnings = [line for line in output.splitlines() if "warning" in line.casefold()]
    for line in warnings:
        print(line, file=sys.stderr)
    if result.returncode:
        print(f"{tool}: obs-document failed with exit code {result.returncode}:\n{output}", file=sys.stderr)
        return 1
    if warnings:
        print(f"{tool}: {len(warnings)} obs warning(s); fix the notes named above", file=sys.stderr)
        return 1
    return 0


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def build(source: Path, destination: Path) -> int:
    """Build the manifest ``source`` into ``destination`` from a copy of its folder (``reading_copy``)."""
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
        config = Path(scratch) / "obs-config.json"
        config.write_text(json.dumps(CORE_CONFIG), encoding="utf-8")
        code = obs_document(obs, ["--config", str(config), "--source", str(vault / source.name),
                                  "--destination", str(destination)], "build_docs", renamed=(vault, folder))
    if code == 0:
        print(f"build_docs: built {destination}")
    return code


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
            note.write_text(changed, encoding="utf-8")
    return copy


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
    parser.add_argument("--destination", type=Path, required=True,
                        help="the HTML file to write, outside the vault")
    arguments = parser.parse_args(argv)
    return build(arguments.source, arguments.destination)


if __name__ == "__main__":
    sys.exit(main())
