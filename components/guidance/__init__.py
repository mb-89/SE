"""SE's guidance commands as a kern component: se_guidance.py's own code answers each command its
component.toml declares (docs/start.md "Commands as components")."""

from pathlib import Path

from se_components import attach

guidance = attach("guidance", "se_guidance", Path(__file__).resolve().parent)
