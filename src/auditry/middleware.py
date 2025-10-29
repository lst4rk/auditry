"""
Request/Response logging middleware with sensitive data redaction.

This middleware integrates with asgi-correlation-id for correlation tracking
and uses structlog for structured logging output.
"""

import json
import re
import time
from typing import Any, Dict, Optional

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse

from .correlation import get_correlation_id
from .redaction import redact_data, redact_headers
from .models import ObservabilityConfig


logger = structlog.get_logger(__name__)


class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to automatically log all request/response activity.

    Captures comprehensive request and response data including payloads,
    headers, timing, and user context. Integrates with asgi-correlation-id
    for distributed tracing.

    Note: This middleware should be added AFTER CorrelationIdMiddleware
    from asgi-correlation-id to ensure correlation IDs are available.
    """

    def __init__(self, app, config: Optional[ObservabilityConfig] = None):
        """
        Initialize logging middleware.

        Args:
            app: FastAPI application instance
            config: Optional configuration for logging behavior
        """
        super().__init__(app)
        self.config = config or ObservabilityConfig()

    async def dispatch(self, request: Request, call_next):
        """
        Process request/response cycle with comprehensive logging.

        Captures request details, processes through application handlers,
        captures response, and logs complete interaction with timing.

        Logging strategy:
        - On success: Log once with both request and response data
        - On failure: Log the request data with error details
        """
        # Get correlation ID from context (set by CorrelationIdMiddleware)
        correlation_id = get_correlation_id()

        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        execution_start_time = time.time()

        request_data = await self._capture_request(request, correlation_id)

        if request_data.get("user_id"):
            structlog.contextvars.bind_contextvars(user_id=request_data["user_id"])

        try:
            # Process the request
            response = await call_next(request)

            execution_duration_ms = (time.time() - execution_start_time) * 1000

            # Capture response details
            response_data = await self._capture_response(response, execution_duration_ms)

            # Add correlation ID to response headers
            if correlation_id:
                response.headers[self.config.correlation_id_header] = correlation_id

            # Check if this is a business event and extract context
            business_event_data = self._extract_business_event(
                request, request_data, response_data
            )

            # Log successful request completion with both request and response data
            log_data = {
                "service": self.config.service_name,
                "request": request_data,
                "response": response_data,
                "execution_duration_ms": execution_duration_ms,
            }

            # Add business event data if this endpoint is tracked
            if business_event_data:
                log_data.update(business_event_data)

            logger.info(
                f"Request completed: {request.method} {request.url.path} - "
                f"Status: {response.status_code} - Duration: {execution_duration_ms:.2f}ms",
                **log_data,
            )

            return response

        except Exception as e:
            execution_duration_ms = (time.time() - execution_start_time) * 1000

            # Log error with full request context
            logger.error(
                f"Request failed: {request.method} {request.url.path} - "
                f"Error: {type(e).__name__}: {str(e)} - Duration: {execution_duration_ms:.2f}ms",
                service=self.config.service_name,
                request=request_data,
                exception_type=type(e).__name__,
                exception_message=str(e),
                execution_duration_ms=execution_duration_ms,
                exc_info=True,
            )
            # Re-raise to let FastAPI's exception handlers deal with it
            raise

    async def _capture_request(self, request: Request, correlation_id: Optional[str]) -> Dict[str, Any]:
        """
        Capture all relevant request details for logging.

        Extracts method, path, headers, query params, body, and user info.
        Applies redaction and size limits to protect sensitive data.
        """
        # Extract user ID from request state (set by auth middleware/dependencies)
        # Simplified to support two common patterns:
        # 1. request.state.user_id (direct ID)
        # 2. request.state.user.id (AuthenticatedUser object)
        user_id = None
        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id
        elif hasattr(request.state, "user") and hasattr(request.state.user, "id"):
            user_id = request.state.user.id

        # Capture headers (with redaction)
        headers = None
        if self.config.log_request_headers:
            headers = redact_headers(dict(request.headers))

        # Capture query params
        query_params = None
        if self.config.log_query_params:
            query_params = dict(request.query_params)

        # Capture request body
        body = await self._capture_request_body(request)

        return {
            "method": request.method,
            "path": request.url.path,
            "query_params": query_params,
            "headers": headers,
            "body": body,
            "user_id": user_id,
            "correlation_id": correlation_id,
        }

    def _parse_body_bytes(self, body_bytes: bytes) -> Optional[Any]:
        """
        Parse body bytes with size limiting and JSON detection.

        Truncates large payloads and attempts JSON parsing with redaction.
        """
        if not body_bytes:
            return None

        # Check size limit
        if len(body_bytes) > self.config.payload_size_limit:
            return {
                "_truncated": True,
                "_original_size": len(body_bytes),
                "_preview": body_bytes[: self.config.payload_size_limit].decode(
                    "utf-8", errors="replace"
                ),
            }

        # Try to parse as JSON
        try:
            body_json = json.loads(body_bytes)
            # Apply redaction to body
            return redact_data(body_json, self.config.additional_redaction_patterns)
        except json.JSONDecodeError:
            # Not JSON, return as string
            return body_bytes.decode("utf-8", errors="replace")

    async def _capture_request_body(self, request: Request) -> Optional[Any]:
        """
        Capture and parse request body with size limiting.

        Attempts to parse JSON bodies. Truncates large payloads to
        prevent excessive log volume.
        """
        try:
            body_bytes = await request.body()
            return self._parse_body_bytes(body_bytes)
        except Exception as e:
            logger.warning(f"Failed to capture request body: {e}")
            return None

    async def _capture_response(self, response: Response, duration_ms: float) -> Dict[str, Any]:
        """
        Capture response details for logging.

        Extracts status code, headers, and body. Handles streaming
        responses by capturing body chunks.
        """
        # Capture headers (with redaction)
        headers = None
        if self.config.log_response_headers:
            headers = redact_headers(dict(response.headers))

        # Capture response body
        body = await self._capture_response_body(response)

        return {
            "status_code": response.status_code,
            "headers": headers,
            "body": body,
            "duration_ms": duration_ms,
        }

    async def _capture_response_body(self, response: Response) -> Optional[Any]:
        """
        Capture and parse response body with size limiting.

        Handles regular responses and streaming responses. Truncates
        large payloads to prevent excessive log volume.
        """
        try:
            # For streaming responses, we can't easily capture the body without consuming it
            if isinstance(response, StreamingResponse):
                return {"_streaming": True, "_message": "Streaming response body not captured"}

            # Get body if available
            if hasattr(response, "body"):
                return self._parse_body_bytes(response.body)

            return None

        except Exception as e:
            logger.warning(f"Failed to capture response body: {e}")
            return None

    def _extract_business_event(
        self,
        request: Request,
        request_data: Dict[str, Any],
        response_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Check if this request matches a configured business event and extract relevant fields.

        Returns dict with event_type and business_context if matched, None otherwise.
        """
        if not self.config.business_events:
            return None

        # Build endpoint pattern: "METHOD /path"
        endpoint_pattern = f"{request.method} {request.url.path}"

        # Check each configured business event
        for pattern, event_config in self.config.business_events.items():
            if self._matches_endpoint_pattern(endpoint_pattern, pattern):
                # Extract business context fields
                business_context = {}

                # Extract from request body
                if event_config.extract_from_request and request_data.get("body"):
                    request_body = request_data["body"]
                    if isinstance(request_body, dict):
                        for field in event_config.extract_from_request:
                            if field in request_body:
                                business_context[field] = request_body[field]

                # Extract from response body
                if event_config.extract_from_response and response_data.get("body"):
                    response_body = response_data["body"]
                    if isinstance(response_body, dict):
                        for field in event_config.extract_from_response:
                            if field in response_body:
                                business_context[field] = response_body[field]

                # Extract from path parameters
                if event_config.extract_from_path:
                    path_params = self._extract_path_params(request.url.path, pattern)
                    for param in event_config.extract_from_path:
                        if param in path_params:
                            business_context[param] = path_params[param]

                return {
                    "event_type": event_config.event_type,
                    "business_context": business_context,
                }

        return None

    def _matches_endpoint_pattern(self, endpoint: str, pattern: str) -> bool:
        """
        Check if an endpoint matches a pattern.

        Supports exact matches and path parameter patterns like /folders/{folder_id}
        """
        # Extract method and path
        endpoint_parts = endpoint.split(" ", 1)
        pattern_parts = pattern.split(" ", 1)

        if len(endpoint_parts) != 2 or len(pattern_parts) != 2:
            return False

        endpoint_method, endpoint_path = endpoint_parts
        pattern_method, pattern_path = pattern_parts

        # Method must match exactly
        if endpoint_method != pattern_method:
            return False

        # Convert pattern to regex (handle {param} placeholders)
        pattern_regex = re.sub(r"\{[^}]+\}", r"[^/]+", pattern_path)
        pattern_regex = f"^{pattern_regex}$"

        return bool(re.match(pattern_regex, endpoint_path))

    def _extract_path_params(self, path: str, pattern: str) -> Dict[str, str]:
        """
        Extract path parameters from a path based on a pattern.

        Example:
            path = "/folders/123"
            pattern = "DELETE /folders/{folder_id}"
            returns {"folder_id": "123"}
        """
        # Extract just the path part from pattern
        pattern_path = pattern.split(" ", 1)[1] if " " in pattern else pattern

        # Find parameter names in pattern
        param_names = re.findall(r"\{([^}]+)\}", pattern_path)

        if not param_names:
            return {}

        # Convert pattern to regex with capture groups
        pattern_regex = re.sub(r"\{[^}]+\}", r"([^/]+)", pattern_path)
        pattern_regex = f"^{pattern_regex}$"

        # Match and extract values
        match = re.match(pattern_regex, path)
        if not match:
            return {}

        # Build dict of param_name -> value
        return dict(zip(param_names, match.groups()))