"""Compatibility module alias for :mod:`app.api.workspace.controller`."""

import sys as _sys

from .api.workspace import controller as _controller

_sys.modules[__name__] = _controller
