"""Compatibility alias for app.application.qa.retrieval_service."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("app.application.qa.retrieval_service")
