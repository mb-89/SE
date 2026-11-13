"""SE's retro commands as a kern component: retro.py's own code answers each command its
component.toml declares (README "Commands as components"). The Go package beside it is SE's
retro-due derivation, which the se binary carries (components/README.md)."""

from pathlib import Path

from se_components import attach

retro = attach("retro", "retro", Path(__file__).resolve().parent)
