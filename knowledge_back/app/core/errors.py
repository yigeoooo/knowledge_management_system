"""Errors exposed by application use cases.

The HTTP adapter translates :class:`ApiError` into the public JSON response;
services can raise it without importing a Flask blueprint.
"""

from .http import ApiError

__all__ = ["ApiError"]
