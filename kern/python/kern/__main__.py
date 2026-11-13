"""``python -m kern run <folder>``: a component's process (:mod:`kern.runner`)."""

import sys

from .runner import main

sys.exit(main())
