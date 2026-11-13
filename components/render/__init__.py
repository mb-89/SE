"""The pages SE renders as a kern component: timeline.py's and deck.py's own code answers each
command its component.toml declares (README "Commands as components")."""

from pathlib import Path

from se_components import attach

render = attach("render", ("timeline", "deck"), Path(__file__).resolve().parent)
