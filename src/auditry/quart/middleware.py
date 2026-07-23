"""Quart observability middleware."""
import time

from quart import Quart, Request, Response, request
from quart.wrappers.response import IterableBody
from asgi_correlation_id import CorrelationIdMiddleware

from ..core import BaseMiddleware, RequestResponseLogger
from ..core.exceptions import resolve_exception_mapping
from ..correlation import get_correlation_id
from ..models import ObservabilityConfig
from ..path_matcher import should_exclude_path
from .adapters import QuartRequestAdapter, QuartResponseAdapter


class QuartMiddleware(BaseMiddleware):
    """Quart middleware with logging and correlation."""

    def __init__(self, app: Quart, config: ObservabilityConfig):
        self.app = app
        self.config = config
        self.logger = RequestResponseLogger(config)
        self.request_adapter = QuartRequestAdapter()
        self.response_adapter = QuartResponseAdapter()

        self._setup_correlation_middleware()
        self._register_hooks()

    def _setup_correlation_middleware(self):
        """Setup correlation ID middleware."""
        original_asgi = self.app.asgi_app
        correlation_app = CorrelationIdMiddleware(
            app=original_asgi,
            header_name=self.config.correlation_id_header,
        )
        self.app.asgi_app = correlation_app

    def _register_hooks(self):
        """Register Quart before_request and after_request hooks."""

        @self.app.before_request
        async def capture_request_start():
            """Hook for request start."""
            # Early exit for excluded paths
            if should_exclude_path(request.path, request.method, self.config.excluded_paths):
                setattr(request, 'observability_excluded', True)
                setattr(request, 'observability_correlation_id', get_correlation_id())
                # Kept for exception-mapping duration on excluded paths
                setattr(request, 'observability_start_time', time.time())
                return

            request.observability_start_time = time.time()
            request.observability_correlation_id = get_correlation_id()
            request.observability_excluded = False

            # extract and cache request body early
            raw_request_data = await self.request_adapter.extract_all(request)
            request.observability_raw_data = raw_request_data

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
                # hands off the stream
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
            # Excluded paths are fully bypassed unless the service opts in to
            # surfacing mapped exceptions there.
            excluded = getattr(request, "observability_excluded", False)
            if excluded and not self.config.map_exceptions_on_excluded_paths:
                raise

            # Configured exception mapping: return a clean, handled response
            # instead of re-raising.
            mapping = resolve_exception_mapping(error, self.config.exception_mappings)

            if excluded:
                if mapping is None:
                    raise
                start_time = getattr(request, "observability_start_time", None)
                self.logger.log_handled_error(
                    request_data={"method": request.method, "path": request.path},
                    error=error,
                    mapping=mapping,
                    duration_ms=(time.time() - start_time) * 1000 if start_time else 0.0,
                    correlation_id=getattr(request, "observability_correlation_id", None),
                )
                return mapping.body, mapping.status_code

            # Check if we have request data
            if hasattr(request, "observability_start_time"):
                duration_ms = (time.time() - request.observability_start_time) * 1000
                correlation_id = getattr(request, "observability_correlation_id", None)
                request_data = getattr(request, "observability_request_data", {})

                # Get user_id if available
                user_id = await self.request_adapter.extract_user_id(request)

                if mapping is not None:
                    # Log the handled failure at the configured level
                    self.logger.log_handled_error(
                        request_data=request_data,
                        error=error,
                        mapping=mapping,
                        duration_ms=duration_ms,
                        correlation_id=correlation_id,
                        user_id=user_id,
                    )
                else:
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

            if mapping is not None:
                # Mark excluded so the after_request hook adds the correlation
                # header via its existing path without logging this response a
                # second time. Quart jsonifies the dict return.
                request.observability_excluded = True
                return mapping.body, mapping.status_code

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