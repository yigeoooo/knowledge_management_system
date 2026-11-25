"""Compatibility alias for app.application.audit.operator_service."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("app.application.audit.operator_service")
