"""SE's review commands as a kern component: review.py's own code answers each command its
component.toml declares (docs/start.md "Commands as components")."""

from pathlib import Path

from se_components import attach

review = attach("review", "review", Path(__file__).resolve().parent)
