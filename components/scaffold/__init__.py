"""What SE scaffolds as a kern component: se.py's own code answers each command its
component.toml declares (docs/start.md "Commands as components")."""

from pathlib import Path

from se_components import attach

scaffold = attach("scaffold", "se", Path(__file__).resolve().parent)
