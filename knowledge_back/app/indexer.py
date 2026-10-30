"""Compatibility alias for app.workers.index_worker."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("app.workers.index_worker")
