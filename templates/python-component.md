---
# An ad hoc Python component over NATS, under the ignored .se/components/: what `se component add
# <name>` scaffolds through this template (scripts/se_component.py), its component.toml and its
# __init__.py. scripts/templates.py's docstring (Code templates) owns this note's format.
name: python-component
version: 1.0.0
kind: code
reader: fleet
says: "An ad hoc Python component: its component.toml with one command, and its __init__.py answering it."
tags: ["code", "python"]
applies:
  actions: ["file.write"]
  paths: [".se/components/*/__init__.py"]
  marker_pattern: "# se:template [\\w.-]+/python-component \\d+\\.\\d+\\.\\d+"
adapter:
  lines:
    - pattern: "# se:template [\\w.-]+/python-component 1\\.\\d+\\.\\d+"
      first: true
      says: "the template marker: the first line is `# se:template se/python-component <version>`, the template and version it derives from"
    - pattern: "from kern import component"
      says: "kern's Python SDK: `from kern import component`, which declares and answers the component"
---

## component.toml

````toml
# se:template {{template}} {{version}}
# An ad hoc component scaffolded by `se component add {{name}}` (SE's docs/go-core.md
# "Scripts are ad hoc, components are long-term"). It lives under the ignored
# .se/components/, so it is never tracked; edit it freely, then restart the core.
name = "{{name}}"
contract = 1
help = "{{says}}"

[commands."{{name}} run"]
usage = "{{name}} run [WORDS...]"
summary = "Do the ad hoc work."
group = "Ad hoc"
help = "Replace this with what {{name}} does; the scaffold echoes its words."
class = "batch"
session = true
````

## __init__.py

````python
# se:template {{template}} {{version}}
"""An ad hoc component scaffolded by `se component add` (SE's docs/go-core.md "Scripts
are ad hoc, components are long-term"). Add inputs, outputs, commands or verbs to
component.toml and answer them here; kern's Python SDK is python/kern/ in kern's clone, .se/modules/kern.
"""

from kern import component

{{ident}} = component("{{name}}")


@{{ident}}.command("{{name}} run")
def run(args, inputs, say):
    return {{ident}}.result("ad hoc {{name}} ran: " + " ".join(args))
````
