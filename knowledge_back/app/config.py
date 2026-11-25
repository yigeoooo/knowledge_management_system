"""Compatibility import for the application configuration package.

New code should import :mod:`app.core.config`.  The forwarding function keeps
the historical ``load_dotenv`` patch point available to deployment scripts and
tests while configuration ownership moves into ``core``.
"""

from dotenv import load_dotenv

from .core import config as _config

ROOT = _config.ROOT


def configuration(overrides):
    original_loader = _config.load_dotenv
    _config.load_dotenv = load_dotenv
    try:
        return _config.configuration(overrides)
    finally:
        _config.load_dotenv = original_loader


__all__ = ["ROOT", "configuration", "load_dotenv"]
