---
# A Python module: a file under scripts/ that other scripts import and that runs as no command (a
# command is a python-script). `templates.py scaffold python-module --path <file> --says <line>`
# writes one, and SE's hook refuses a write that leaves a module without its marker or docstring.
# scripts/code_templates.py's docstring owns this note's format.
name: python-module
version: 1.0.0
kind: code
reader: fleet
says: "A Python module scripts import."
tags: ["code", "python"]
applies:
  actions: ["file.write"]
  paths: ["scripts/*.py"]
  marker_pattern: "# se:template [\\w.-]+/python-module \\d+\\.\\d+\\.\\d+"
adapter:
  lines:
    - pattern: "# se:template [\\w.-]+/python-module 1\\.\\d+\\.\\d+"
      first: true
      says: "the template marker: the first line is `# se:template se/python-module <version>`, the template and version it derives from"
    - pattern: "\"\"\"\\S.*"
      says: "the docstring: the module opens with a docstring that says what it is for"
---

## {{name}}.py

````python
# se:template {{template}} {{version}}
"""{{says}}

Slot: say here what the module offers and who imports it.
"""

from __future__ import annotations


def answer() -> str:
    """Slot: the module's own code."""
    return "{{name}}"
````
