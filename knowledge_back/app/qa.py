"""Compatibility module alias for :mod:`app.api.qa.controller`."""

import sys as _sys

from .api.qa import controller as _controller

_sys.modules[__name__] = _controller
