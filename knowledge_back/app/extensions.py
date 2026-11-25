"""Compatibility import for Flask extensions.

The extension instances live in :mod:`app.core.extensions` so application
setup and infrastructure code have one canonical import location.
"""

from .core.extensions import db, limiter, migrate

__all__ = ["db", "limiter", "migrate"]
