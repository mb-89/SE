"""kern's Python SDK: a component in Python, its fake core and its process on the bus.

Standard library only. ``component`` makes a component from the ``component.toml``
beside its code; :mod:`kern.fake` tests it without the core; ``python -m kern run
<folder>`` is its process (:mod:`kern.runner`), over the NATS peer of :mod:`kern.nats`.
SE's docs/go-core.md ("The component contract") is the contract until kern owns it.
"""

from .component import Ask, Component, Inputs, KernError, Result, Write, component
from .declaration import CONTRACT, Declaration, DeclarationError

__all__ = ["Ask", "CONTRACT", "Component", "Declaration", "DeclarationError", "Inputs", "KernError", "Result",
           "Write", "component"]
