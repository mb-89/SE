"""SE's templates commands as a kern component: se_templates.py's own code answers each command its
component.toml declares (docs/start.md "Commands as components")."""

from pathlib import Path

from se_components import attach

templates = attach("templates", "se_templates", Path(__file__).resolve().parent)
