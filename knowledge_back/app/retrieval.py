"""Compatibility module alias for :mod:`app.api.retrieval.controller`."""

import sys as _sys

from .api.retrieval import controller as _controller

_sys.modules[__name__] = _controller
