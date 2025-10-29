"""
Unified observability middleware that handles both correlation IDs and request/response logging.

This middleware combines correlation ID management and comprehensive logging into a single,
easy-to-use middleware that requires minimal configuration.
"""

from typing import Optional

from asgi_correlation_id import CorrelationIdMiddleware as BaseCorrelationIdMiddleware
from starlette.applications import Starlette

from .middleware import RequestResponseLoggingMiddleware
from .models import ObservabilityConfig


class ObservabilityMiddleware:
    """
    Unified middleware for comprehensive observability.

    Combines correlation ID management and request/response logging into a single
    middleware that's easy to configure. Automatically handles proper ordering
    of sub-middlewares.

    Example:
        app = FastAPI()
        app.add_middleware(
            ObservabilityMiddleware,
            config=ObservabilityConfig(service_name="vault-api")
        )
    """

    def __init__(
        self,
        app: Starlette,
        config: Optional[ObservabilityConfig] = None,
    ):
        """
        Initialize the unified observability middleware.

        Args:
            app: FastAPI/Starlette application instance
            config: Observability configuration with service name and options
        """
        if config is None:
            raise ValueError(
                "ObservabilityConfig is required"
            )

        self.app = app
        self.config = config

        # Wrap the app with sub-middlewares in the correct order
        # Order matters: Correlation ID must be set first, then logging can use it

        # 1. First, wrap with logging middleware
        logging_app = RequestResponseLoggingMiddleware(app, config=config)

        # 2. Then wrap with correlation ID middleware
        # This ensures correlation ID is available to the logging middleware
        correlation_app = BaseCorrelationIdMiddleware(
            logging_app,
            header_name=config.correlation_id_header,
        )

        self.wrapped_app = correlation_app

    async def __call__(self, scope, receive, send):
        """
        ASGI application interface.

        Delegates to the wrapped middleware stack.
        """
        await self.wrapped_app(scope, receive, send)