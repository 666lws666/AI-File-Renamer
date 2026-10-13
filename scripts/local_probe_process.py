"""Compatibility alias for the product-owned native process module."""
import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("src.services.local_ai.native.process")
