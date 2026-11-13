"""SE's retro commands as a kern component: retro.py's own code answers each command its
component.toml declares (README "Commands as components"). It is retrospective, as `retro` names
SE's Go retro-due component, which the se binary carries (components/README.md)."""

from pathlib import Path

from se_components import attach

retrospective = attach("retrospective", "retro", Path(__file__).resolve().parent)
