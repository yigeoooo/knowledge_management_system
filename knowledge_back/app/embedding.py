"""Compatibility alias for app.integrations.ai.embedding_adapter."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("app.integrations.ai.embedding_adapter")
