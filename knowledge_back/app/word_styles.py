"""Compatibility alias for app.processors.word.styles."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("app.processors.word.styles")
