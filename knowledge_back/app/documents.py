"""Compatibility module alias for :mod:`app.api.documents.controller`."""

import sys as _sys

from .api.documents import controller as _controller

_sys.modules[__name__] = _controller
