"""SE's overhaul commands as a kern component: overhaul.py's own code answers each command its
component.toml declares (docs/start.md "Commands as components")."""

from pathlib import Path

from se_components import attach

overhaul = attach("overhaul", "overhaul", Path(__file__).resolve().parent)
