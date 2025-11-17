"""FastAPI middleware for observability."""

import time

from fastapi import Request
from asgi_correlation_id import CorrelationIdMiddleware

from ..correlation import get_correlation_id
from ..models import ObservabilityConfig
from ..path_matcher import should_exclude_path
from .adapters import FastAPIRequestAdapter, FastAPIResponseAdapter
from ..core.logger import RequestResponseLogger


class FastAPIMiddleware:
    """ASGI middleware for request/response logging with streaming support."""

    def __init__(self, app, config: ObservabilityConfig):
        self.app = app
        self.config = config
        self.logger = RequestResponseLogger(config)
        self.request_adapter = FastAPIRequestAdapter()
        self.response_adapter = FastAPIResponseAdapter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Create request to check path
        request = Request(scope, receive=receive)
        path = str(request.url.path)
        method = request.method

        # Handle excluded paths - just add correlation ID
        if should_exclude_path(path, method, self.config.excluded_paths):
            async def add_correlation_header(message):
                if message["type"] == "http.response.start":
                    corr_id = get_correlation_id()
                    if corr_id and self.config.correlation_id_header:
                        headers = list(message.get("headers", []))
                        headers.append((self.config.correlation_id_header.encode(), corr_id.encode()))
                        message["headers"] = headers
                await send(message)

            await self.app(scope, receive, add_correlation_header)
            return

        # Buffer the request body for logging
        body_chunks = []
        message = await receive()

        while message["type"] == "http.request":
            body = message.get("body", b"")
            if body:
                body_chunks.append(body)
            if not message.get("more_body", False):
                break
            message = await receive()

        raw_body = b"".join(body_chunks)

        # Simple replay function for the buffered body
        body_sent = False

        async def replay_body():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(scope, receive=replay_body)

        # Prepare logging context
        correlation_id = get_correlation_id()
        start_time = time.time()

        # Extract request data for logging
        raw_request_data = {
            "method": method,
            "path": path,
            "headers": dict(request.headers),
            "query_params": dict(request.query_params),
            "path_params": dict(getattr(request, "path_params", {})),
            "body": raw_body,
            "user_id": await self.request_adapter.extract_user_id(request),
        }
        request_data = self.logger.prepare_request_data(raw_request_data, correlation_id)

        # Capture response info
        response_info = {"status": None, "headers": {}}

        async def capture_response(message):
            if message["type"] == "http.response.start":
                response_info["status"] = message["status"]

                # Capture headers
                for name, value in message.get("headers", []):
                    response_info["headers"][name.decode().lower()] = value.decode()

                # Add correlation ID to response
                if correlation_id and self.config.correlation_id_header:
                    headers = list(message.get("headers", []))
                    headers.append((self.config.correlation_id_header.encode(), correlation_id.encode()))
                    message["headers"] = headers

            await send(message)

        try:
            # Process the request
            await self.app(scope, replay_body, capture_response)

            # Log success
            duration_ms = (time.time() - start_time) * 1000
            user_id = await self.request_adapter.extract_user_id(request)

            self.logger.log_success(
                request_data=request_data,
                response_data={
                    "status_code": response_info["status"],
                    "headers": response_info["headers"],
                    "body": None,  # No response buffering for streaming
                },
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
            )

        except Exception as error:
            # Log error
            duration_ms = (time.time() - start_time) * 1000
            user_id = await self.request_adapter.extract_user_id(request)

            self.logger.log_error(
                request_data=request_data,
                error=error,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                user_id=user_id,
            )
            raise

        finally:
            # Clean up
            self.request_adapter.clear_cache(request)


def create_middleware(app, config: ObservabilityConfig):
    """Create and attach observability middleware to FastAPI app."""
    # Order matters: last added runs first
    app.add_middleware(FastAPIMiddleware, config=config)
    app.add_middleware(CorrelationIdMiddleware, header_name=config.correlation_id_header)
    return app