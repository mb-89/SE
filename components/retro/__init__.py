"""SE's retro commands as a kern component: retro.py's own code answers each command its
component.toml declares (README "Commands as components")."""

from pathlib import Path

from se_components import attach

retro = attach("retro", "retro", Path(__file__).resolve().parent)
