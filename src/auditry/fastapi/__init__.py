"""
FastAPI adapter for auditry observability.

This module provides FastAPI/Starlette-specific implementations for the
observability middleware.
"""

from .adapters import FastAPIRequestAdapter, FastAPIResponseAdapter
from .exceptions import BaseAPIException, ErrorResponse, create_exception_handler
from .middleware import FastAPIMiddleware, create_middleware

__all__ = [
    "FastAPIMiddleware",
    "create_middleware",
    "FastAPIRequestAdapter",
    "FastAPIResponseAdapter",
    "ErrorResponse",
    "BaseAPIException",
    "create_exception_handler",
]
