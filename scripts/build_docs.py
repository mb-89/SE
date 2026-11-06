"""Build se's documentation, one HTML file, from `docs.md` with the obs module.

The README section "Documentation" owns what this builds and where it is published. Exit code 0:
built without a warning; 1: the build failed or obs warned (each warning is printed); 2: setup error.
"""

from __future__ import annotations

import argparse
import json
import os
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


def obs_dir() -> Path:
    """Bring the obs module to its pin in se.toml and return the directory it is used from."""
    for command in ("sync", "path"):
        result = subprocess.run([sys.executable, str(MODULES), command, "obs"], cwd=ROOT,
                                capture_output=True, text=True)
        if result.returncode:
            print(f"build_docs: se_modules.py {command} obs failed:\n{result.stderr}{result.stdout}", file=sys.stderr)
            sys.exit(2)
    return Path(result.stdout.strip().splitlines()[-1])


def child_environment() -> dict[str, str]:
    """This environment without uv's deprecated UV_NATIVE_TLS, whose notice would read as a warning."""
    environment = dict(os.environ)
    if environment.pop("UV_NATIVE_TLS", None):
        environment.setdefault("UV_SYSTEM_CERTS", "1")
    return environment


def build(source: Path, destination: Path) -> int:
    obs = obs_dir()
    with tempfile.TemporaryDirectory() as scratch:
        config = Path(scratch) / "obs-config.json"
        config.write_text(json.dumps(CORE_CONFIG), encoding="utf-8")
        result = subprocess.run(
            ["uv", "run", "--quiet", "--project", str(obs), "obs-document", "--config", str(config),
             "--source", str(source.resolve()), "--adapter", "html", "--adapter-config", str(obs / "adapters.json"),
             "--destination", str(destination.resolve())],
            cwd=ROOT, capture_output=True, text=True, env=child_environment(),
        )
    output = result.stdout + result.stderr
    warnings = [line for line in output.splitlines() if "warning" in line.casefold()]
    for line in warnings:
        print(line, file=sys.stderr)
    if result.returncode:
        print(f"build_docs: obs-document failed with exit code {result.returncode}:\n{output}", file=sys.stderr)
        return 1
    if warnings:
        print(f"build_docs: {len(warnings)} obs warning(s); fix the notes named above", file=sys.stderr)
        return 1
    print(f"build_docs: built {destination}")
    return 0


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
