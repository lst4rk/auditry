"""
Quart middleware implementation for observability.

This module provides the Quart-specific middleware that integrates with
Quart's request/response hooks and uses the core logging functionality.
"""
import time

from quart import Quart, Request, Response, request
from quart.wrappers.response import IterableBody
from asgi_correlation_id import CorrelationIdMiddleware

from ..core import BaseMiddleware, RequestResponseLogger
from ..correlation import get_correlation_id
from ..models import ObservabilityConfig
from ..path_matcher import should_exclude_path
from .adapters import QuartRequestAdapter, QuartResponseAdapter


class QuartMiddleware(BaseMiddleware):
    """
    Quart middleware for observability.

    This middleware integrates with Quart's hook system to provide:
    - Request/response logging
    - Correlation ID tracking
    - Business event extraction
    - Sensitive data redaction
    """

    def __init__(self, app: Quart, config: ObservabilityConfig):
        """
        Initialize Quart middleware and register hooks.

        Args:
            app: Quart application
            config: Observability configuration
        """
        self.app = app
        self.config = config
        self.logger = RequestResponseLogger(config)
        self.request_adapter = QuartRequestAdapter()
        self.response_adapter = QuartResponseAdapter()

        # Apply correlation ID middleware at ASGI level
        self._setup_correlation_middleware()

        # Register request/response hooks
        self._register_hooks()

    def _setup_correlation_middleware(self):
        """Wrap the Quart app with correlation ID middleware at the ASGI level."""
        # Store the original ASGI app
        original_asgi = self.app.asgi_app

        # Wrap with correlation ID middleware
        correlation_app = CorrelationIdMiddleware(
            app=original_asgi,
            header_name=self.config.correlation_id_header,
        )

        # Replace the ASGI app
        self.app.asgi_app = correlation_app

    def _register_hooks(self):
        """Register Quart before_request and after_request hooks."""

        @self.app.before_request
        async def capture_request_start():
            """Capture request start time and initial data."""
            # Check if this path is excluded from observability
            if should_exclude_path(request.path, request.method, self.config.excluded_paths):
                request.observability_excluded = True
                # Still set correlation ID for excluded paths (useful for tracing)
                request.observability_correlation_id = get_correlation_id()
                return

            # Store timing and correlation data
            request.observability_start_time = time.time()
            request.observability_correlation_id = get_correlation_id()
            request.observability_excluded = False

            # Pre-extract request data (especially body which needs caching)
            raw_request_data = await self.request_adapter.extract_all(request)
            request.observability_raw_data = raw_request_data

            # Prepare request data for logging
            request.observability_request_data = self.logger.prepare_request_data(
                raw_request_data,
                request.observability_correlation_id
            )

        @self.app.after_request
        async def log_request_response(response: Response) -> Response:
            """Log the request/response after processing."""
            # Check if this path was excluded
            if getattr(request, "observability_excluded", False):
                # Still add correlation ID to response headers for excluded paths
                correlation_id = getattr(request, "observability_correlation_id", None)
                if correlation_id and self.config.correlation_id_header:
                    response.headers[self.config.correlation_id_header] = correlation_id
                return response

            # Check if we have request data (might not if before_request wasn't called)
            if not hasattr(request, "observability_start_time"):
                return response

            # Check if this is a streaming response - if so, handle it separately
            if hasattr(response, "response") and isinstance(response.response, IterableBody):
                # For streaming responses, log without consuming the stream
                duration_ms = (time.time() - request.observability_start_time) * 1000

                # Get stored correlation ID from before_request
                correlation_id = getattr(request, "observability_correlation_id", None)
                request_data = getattr(request, "observability_request_data", {})

                # Re-extract user_id (might have been set during request processing)
                user_id = await self.request_adapter.extract_user_id(request)

                # Log with minimal response data (no body for streaming)
                self.logger.log_success(
                    request_data=request_data,
                    response_data={
                        "status_code": response.status_code if hasattr(response, "status_code") else 200,
                        "headers": dict(response.headers) if hasattr(response, "headers") else {},
                        "body": None  # Don't try to extract body for streaming
                    },
                    duration_ms=duration_ms,
                    correlation_id=correlation_id,
                    user_id=user_id,
                )

                # Add correlation ID to response headers (same as non-streaming)
                if correlation_id:
                    response.headers[self.config.correlation_id_header] = correlation_id

                # Clear cache and return immediately
                self.request_adapter.clear_cache(request)
                return response

            # Non-streaming response handling
            # Calculate duration
            duration_ms = (time.time() - request.observability_start_time) * 1000

            # Get stored data
            correlation_id = getattr(request, "observability_correlation_id", None)
            request_data = getattr(request, "observability_request_data", {})

            # Re-extract user_id (might have been set during request processing)
            user_id = await self.request_adapter.extract_user_id(request)

            # Extract and prepare response data
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

            # Clear cache
            self.request_adapter.clear_cache(request)

            return response

        @self.app.errorhandler(Exception)
        async def handle_exception(error: Exception):
            """Log errors with request context."""
            # Check if this path was excluded
            if getattr(request, "observability_excluded", False):
                raise

            # Check if we have request data
            if hasattr(request, "observability_start_time"):
                duration_ms = (time.time() - request.observability_start_time) * 1000
                correlation_id = getattr(request, "observability_correlation_id", None)
                request_data = getattr(request, "observability_request_data", {})

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

                # Clear cache
                self.request_adapter.clear_cache(request)

            # Re-raise for Quart's error handlers
            raise

    async def process_request(self, request: Request, call_next) -> Response:
        """
        Process a request through the middleware pipeline.

        Note: This method is here to satisfy the BaseMiddleware interface,
        but Quart uses hooks instead of a middleware chain pattern.
        The actual processing happens in the registered hooks.

        Args:
            request: The incoming Quart request
            call_next: Not used in Quart implementation

        Returns:
            The Quart response
        """
        # This method is not directly used in Quart
        # The hooks handle the middleware functionality
        raise NotImplementedError(
            "Quart uses hooks instead of middleware chain. "
            "Use the QuartMiddleware constructor to register hooks."
        )


def create_middleware(app: Quart, config: ObservabilityConfig) -> Quart:
    """
    Create and configure the complete Quart middleware stack.

    This function sets up correlation ID middleware and logging hooks.

    Args:
        app: Quart application
        config: Observability configuration

    Returns:
        The configured Quart application

    Example:
        ```python
        from quart import Quart
        from auditry.quart import create_middleware
        from auditry import ObservabilityConfig

        app = Quart(__name__)

        # Apply observability middleware
        app = create_middleware(
            app,
            config=ObservabilityConfig(service_name="my-service")
        )
        ```
    """
    # Create and register the middleware
    QuartMiddleware(app, config)

    return app