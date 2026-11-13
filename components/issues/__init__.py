"""SE's issues commands as a kern component: work_tickets.py's own code answers each command its
component.toml declares (README "Commands as components")."""

from pathlib import Path

from se_components import attach

issues = attach("issues", "work_tickets", Path(__file__).resolve().parent)
