"""
Auditry - Observability middleware for Python web frameworks.

This package provides comprehensive request/response logging, correlation ID tracking,
business event extraction, and sensitive data redaction for FastAPI and Quart applications.

Basic Usage:

    FastAPI:
    ```python
    from fastapi import FastAPI
    from auditry.fastapi import create_middleware
    from auditry import ObservabilityConfig

    app = FastAPI()
    app = create_middleware(app, ObservabilityConfig(service_name="my-api"))
    ```

    Quart:
    ```python
    from quart import Quart
    from auditry.quart import create_middleware
    from auditry import ObservabilityConfig

    app = Quart(__name__)
    app = create_middleware(app, ObservabilityConfig(service_name="my-api"))
    ```
"""

from .logging_config import configure_logging, get_logger
from .correlation import get_correlation_id
from .models import ObservabilityConfig, BusinessEventConfig

__version__ = "0.2.6"

__all__ = [
    # Configuration
    "ObservabilityConfig",
    "BusinessEventConfig",
    # Logging
    "configure_logging",
    "get_logger",
    # Utilities
    "get_correlation_id",
]