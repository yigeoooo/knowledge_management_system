"""Compatibility alias for app.processors.answer_text."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("app.processors.answer_text")
