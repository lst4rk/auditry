"""Core framework-agnostic observability logic."""

from .base import (
    BaseRequestAdapter,
    BaseResponseAdapter,
    BaseMiddleware,
)
from .logger import RequestResponseLogger

__all__ = [
    "BaseRequestAdapter",
    "BaseResponseAdapter",
    "BaseMiddleware",
    "RequestResponseLogger",
]