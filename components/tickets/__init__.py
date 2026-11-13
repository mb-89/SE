"""SE's tickets commands as a kern component: work_tickets.py's own code answers each command its
component.toml declares (README "Commands as components")."""

from pathlib import Path

from se_components import attach

tickets = attach("tickets", "work_tickets", Path(__file__).resolve().parent)
