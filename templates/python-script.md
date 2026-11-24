---
# A Python script: a file under scripts/ that runs as a command. Its shape is fixed (the uv entry,
# argparse help, logging, all through the shared library scripts/se_script.py); the author fills
# only the slots. `templates.py scaffold python-script --path <file> --says <line>` writes one, and
# SE's hook refuses a write that leaves a script off this shape. scripts/templates.py's docstring
# (Code templates) owns this note's format.
name: python-script
version: 1.0.0
kind: code
reader: fleet
says: "A Python script: the uv entry, argparse help and logging through scripts/se_script.py, and slots for its own part."
tags: ["code", "python", "script"]
applies:
  actions: ["file.write"]
  paths: ["scripts/*.py"]
  marker_pattern: "# se:template [\\w.-]+/python-script \\d+\\.\\d+\\.\\d+"
adapter:
  lines:
    - pattern: "#!/usr/bin/env -S uv run python"
      first: true
      says: "the uv entry: the first line is `#!/usr/bin/env -S uv run python`, so the script runs through uv"
    - pattern: "# se:template [\\w.-]+/python-script 1\\.\\d+\\.\\d+"
      says: "the template marker: the second line is `# se:template se/python-script <version>`, the template and version it derives from"
    - pattern: "import se_script"
      says: "the shared library: `import se_script` (scripts/se_script.py), which carries the uv entry, the help and the logging"
    - pattern: ".*\\bse_script\\.parser\\(.*"
      says: "help: the parser is `se_script.parser(...)`, argparse's with the full help and the logging epilog"
    - pattern: "(raise SystemExit|sys\\.exit)\\(se_script\\.run\\(main\\)\\)"
      says: "the entry: the `__main__` block ends `raise SystemExit(se_script.run(main))`, which sets up logging and runs main"
---

## {{name}}.py

````python
#!/usr/bin/env -S uv run python
# se:template {{template}} {{version}}
"""{{says}}

Usage: `uv run python scripts/{{name}}.py --help`. Slot: say here what the script reads, writes and
answers, as its readers need it; the help prints this text.
"""

from __future__ import annotations

import argparse
import logging

import se_script

LOG = logging.getLogger(__name__)


def make_parser() -> argparse.ArgumentParser:
    """The script's parser: the library's, with the script's own arguments (slot)."""
    parser = se_script.parser(prog="{{name}}.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("words", nargs="*", help="slot: the script's own arguments")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the script on `argv`; its exit code."""
    options = make_parser().parse_args(argv)
    LOG.info("{{name}}: %d words", len(options.words))
    # Slot: the script's own logic.
    print(" ".join(options.words))
    return 0


if __name__ == "__main__":
    raise SystemExit(se_script.run(main))
````
