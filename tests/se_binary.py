"""The se binary the tests that run it take (tests/conftest.py `se_binary`): setup.sh and setup.ps1
run its `stopped-hooks` (components/start).

It is built from components/ once per tree and kept in `.se/.runtime/test-se/<build key>`, so a
later run of the same tree builds nothing. `uv run python tests/se_binary.py` places kern at its pin
and builds it: the complete suite's setup (se.toml `[tests] setup`), which the suite's budget does
not count, so no budgeted test waits for a cold Go build.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import process_door  # noqa: E402
import se_modules  # noqa: E402

KERN = se_modules.kern_dir(ROOT)


def key() -> str:
    """What the binary is built from: every Go source, go.mod and go.sum under components/ but its
    tests and testdata, and kern's commit, as one digest."""
    digest = hashlib.sha256()
    components = ROOT / "components"
    for path in sorted(components.rglob("*")):
        name = path.relative_to(components).as_posix()
        if (path.is_file() and not name.endswith("_test.go") and "/testdata/" not in f"/{name}"
                and path.suffix in (".go", ".mod", ".sum")):
            digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    try:
        digest.update((KERN / ".git" / "HEAD").read_bytes())
    except OSError:
        pass
    return digest.hexdigest()[:16]


def path() -> Path:
    """Where the binary of this tree is kept."""
    return ROOT / ".se" / ".runtime" / "test-se" / key() / ("se.exe" if os.name == "nt" else "se")


def build(binary: Path) -> str:
    """Build `binary` with go from components/; the error where it failed, else ""."""
    part = binary.with_name(binary.name + f".part{os.getpid()}")
    part.parent.mkdir(parents=True, exist_ok=True)
    built = process_door.run(["go", "build", "-o", str(part), "./cmd/se"], cwd=ROOT / "components",
                             capture_output=True, text=True, check=False)
    if built.returncode:
        return f"go build ./cmd/se failed:\n{built.stderr}"
    part.replace(binary)
    return ""


def main(argv: list[str] | None = None) -> int:
    """Place kern at its pin and build the binary of this tree where it is missing; exit code 1
    where either failed."""
    synced = process_door.run([sys.executable, str(ROOT / "scripts" / "se_modules.py"), "sync", se_modules.KERN],
                              cwd=ROOT, capture_output=True, text=True, check=False)
    if synced.returncode:
        print(f"se_binary: se_modules.py sync kern failed:\n{synced.stderr}{synced.stdout}", file=sys.stderr)
        return 1
    binary = path()
    if binary.is_file():
        print(f"se_binary: in place: {binary}")
        return 0
    if error := build(binary):
        print(f"se_binary: {error}", file=sys.stderr)
        return 1
    print(f"se_binary: built: {binary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
