"""SE's forms commands as a kern component: se_forms.py's own code answers each command its
component.toml declares (README "Commands as components")."""

from pathlib import Path

from se_components import attach

forms = attach("forms", "se_forms", Path(__file__).resolve().parent)
