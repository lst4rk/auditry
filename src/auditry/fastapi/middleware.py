"""
FastAPI/Starlette middleware implementation for observability.

This module provides the FastAPI-specific middleware that integrates with
the Starlette middleware system and uses the core logging functionality.
"""

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse
from asgi_correlation_id import CorrelationIdMiddleware

from ..core import BaseMiddleware, RequestResponseLogger
from ..correlation import get_correlation_id
from ..models import ObservabilityConfig
from ..path_matcher import should_exclude_path
from .adapters import FastAPIRequestAdapter, FastAPIResponseAdapter


class FastAPIMiddleware(BaseHTTPMiddleware, BaseMiddleware):
    """
    FastAPI/Starlette middleware for observability.

    This middleware integrates with FastAPI's middleware system to provide:
    - Request/response logging
    - Correlation ID tracking
    - Business event extraction
    - Sensitive data redaction
    """

    def __init__(self, app, config: ObservabilityConfig):
        """
        Initialize FastAPI middleware.

        Args:
            app: FastAPI or Starlette application
            config: Observability configuration
        """
        # Initialize Starlette base middleware
        super().__init__(app)

        # Store configuration and initialize components
        self.config = config
        self.logger = RequestResponseLogger(config)
        self.request_adapter = FastAPIRequestAdapter()
        self.response_adapter = FastAPIResponseAdapter()

    async def dispatch(self, request: Request, call_next):
        """
        Process request through the middleware.

        This is the Starlette middleware pattern entry point.

        Args:
            request: The incoming request
            call_next: The next handler in the chain

        Returns:
            The response from the application
        """
        return await self.process_request(request, call_next)

    async def process_request(self, request: Request, call_next) -> Response:
        """
        Process a request through the middleware pipeline.

        This method:
        1. Captures request data
        2. Calls the application
        3. Captures response data
        4. Logs everything
        5. Returns the response

        Args:
            request: The incoming FastAPI request
            call_next: The next handler in the chain

        Returns:
            The FastAPI response
        """
        # Check if this path is excluded from observability
        path = str(request.url.path)
        method = request.method
        if should_exclude_path(path, method, self.config.excluded_paths):
            # For excluded paths, just pass through with correlation ID
            response = await call_next(request)
            correlation_id = get_correlation_id()
            if correlation_id and self.config.correlation_id_header:
                response.headers[self.config.correlation_id_header] = correlation_id
            return response

        # Get correlation ID (set by correlation middleware if present)
        correlation_id = get_correlation_id()

        # Start timing
        start_time = time.time()

        # Extract request data
        raw_request_data = await self.request_adapter.extract_all(request)

        # Prepare request data for logging
        request_data = self.logger.prepare_request_data(
            raw_request_data,
            correlation_id
        )

        try:
            # Process the request
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Re-extract user_id (might have been set by auth middleware)
            user_id = await self.request_adapter.extract_user_id(request)

            # Handle response data extraction based on response type
            if isinstance(response, StreamingResponse):
                # For streaming responses, log without consuming the stream
                response_data = {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": None
                }
            else:
                # For non-streaming responses, extract full response data
                raw_response_data = await self.response_adapter.extract_all(response)
                response_data = self.logger.prepare_response_data(raw_response_data)

            # Add correlation ID to response headers
            if correlation_id and self.config.correlation_id_header:
                response.headers[self.config.correlation_id_header] = correlation_id

            # Log successful request
            self.logger.log_success(
                request_data=request_data,
                response_data=response_data,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
            )

            return response

        except Exception as error:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Get user_id if available
            user_id = await self.request_adapter.extract_user_id(request)

            # Log the error
            self.logger.log_error(
                request_data=request_data,
                error=error,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
            )

            # Re-raise for FastAPI's error handlers
            raise

        finally:
            # Clear request body cache
            self.request_adapter.clear_cache(request)


def create_middleware(app, config: ObservabilityConfig):
    """
    Create and configure the complete FastAPI middleware stack.

    This function sets up both correlation ID and logging middleware
    in the correct order.

    Args:
        app: FastAPI or Starlette application
        config: Observability configuration

    Returns:
        The configured middleware instance

    Example:
        ```python
        from fastapi import FastAPI
        from auditry.fastapi import create_middleware
        from auditry import ObservabilityConfig

        app = FastAPI()

        # Add correlation ID middleware first
        app.add_middleware(
            CorrelationIdMiddleware,
            header_name="X-Correlation-ID"
        )

        # Then add observability middleware
        app.add_middleware(
            FastAPIMiddleware,
            config=ObservabilityConfig(service_name="my-service")
        )
        ```
    """
    # Note: In FastAPI, middleware is added in reverse order
    # The last middleware added is executed first

    # Add logging middleware
    app.add_middleware(
        FastAPIMiddleware,
        config=config
    )

    # Add correlation ID middleware (will be executed first)
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name=config.correlation_id_header
    )

    return app