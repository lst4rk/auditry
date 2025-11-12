"""FastAPI middleware for observability."""

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
    """FastAPI observability middleware."""

    def __init__(self, app, config: ObservabilityConfig):
        super().__init__(app)
        self.config = config
        self.logger = RequestResponseLogger(config)
        self.request_adapter = FastAPIRequestAdapter()
        self.response_adapter = FastAPIResponseAdapter()

    async def dispatch(self, request: Request, call_next):
        """Starlette middleware entry point."""
        return await self.process_request(request, call_next)

    async def process_request(self, request: Request, call_next) -> Response:
        """Process and log the request/response."""
        # check exclusions first
        req_path = str(request.url.path)
        req_method = request.method
        if should_exclude_path(req_path, req_method, self.config.excluded_paths):
            resp = await call_next(request)
            corr_id = get_correlation_id()
            if corr_id and self.config.correlation_id_header:
                resp.headers[self.config.correlation_id_header] = corr_id
            return resp

        correlation_id = get_correlation_id()
        start_time = time.time()

        raw_request_data = await self.request_adapter.extract_all(request)
        request_data = self.logger.prepare_request_data(
            raw_request_data,
            correlation_id
        )

        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            # re-check user_id in case auth middleware set it
            user_id = await self.request_adapter.extract_user_id(request)

            if isinstance(response, StreamingResponse):
                # streaming responses are tricky - don't consume them
                response_data = {
                    'status_code': response.status_code,
                    'headers': dict(response.headers),
                    'body': None
                }
            else:
                raw_response_data = await self.response_adapter.extract_all(response)
                response_data = self.logger.prepare_response_data(raw_response_data)

            if correlation_id and self.config.correlation_id_header:
                response.headers[self.config.correlation_id_header] = correlation_id

            self.logger.log_success(
                request_data=request_data,
                response_data=response_data,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
            )

            return response

        except Exception as error:
            duration_ms = (time.time() - start_time) * 1000
            user_id = await self.request_adapter.extract_user_id(request)

            self.logger.log_error(
                request_data=request_data,
                error=error,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
            )
            raise  # let FastAPI handle it

        finally:
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