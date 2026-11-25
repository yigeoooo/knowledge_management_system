"""Compatibility alias for app.integrations.storage.minio_adapter."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("app.integrations.storage.minio_adapter")
