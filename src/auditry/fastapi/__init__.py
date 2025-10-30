"""
FastAPI adapter for auditry observability.

This module provides FastAPI/Starlette-specific implementations for the
observability middleware.
"""

from .middleware import FastAPIMiddleware, create_middleware
from .adapters import FastAPIRequestAdapter, FastAPIResponseAdapter

__all__ = [
    "FastAPIMiddleware",
    "create_middleware",
    "FastAPIRequestAdapter",
    "FastAPIResponseAdapter",
]