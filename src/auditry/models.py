from typing import Any, Dict, List, Literal, Optional, Type, Union
from pydantic import BaseModel, Field, field_validator


class BusinessEventConfig(BaseModel):
    """
    Configuration for a business event to track.

    Defines what event type to tag and what fields to extract for analytics.
    """

    event_type: str = Field(
        description="Business event type (e.g., 'folder.created', 'file.uploaded')"
    )
    extract_from_request: Optional[List[str]] = Field(
        default=None,
        description="Field names to extract from request body for business context"
    )
    extract_from_response: Optional[List[str]] = Field(
        default=None,
        description="Field names to extract from response body for business context"
    )
    extract_from_path: Optional[List[str]] = Field(
        default=None,
        description="Path parameter names to extract (e.g., ['folder_id'] for /folders/{folder_id})"
    )


class ExceptionMapping(BaseModel):
    """
    Map an exception type to a handled HTTP response and log level.

    Matching exceptions are returned as the configured response by the
    middleware instead of re-raising. See README "Exception Mapping".
    """

    exception_type: Type[Exception] = Field(
        description="Exception class to match (subclasses match via isinstance)"
    )
    status_code: int = Field(
        ge=100, le=599,
        description="HTTP status code for the mapped response"
    )
    body: Dict[str, Any] = Field(
        description="JSON body returned as the mapped response"
    )
    log_level: Literal["debug", "info", "warning", "error", "critical"] = Field(
        default="warning",
        description="Log level for the handled failure",
    )


class ObservabilityConfig(BaseModel):
    """
    Configuration options for observability logging behavior.

    Allows services to customize logging behavior including payload
    size limits, redaction patterns, and verbosity.
    """

    service_name: str = Field(
        min_length=1,
        description="Name of the service for logging context (e.g., 'vault-api', 'auth-service')"
    )
    correlation_id_header: str = Field(
        default="X-Request-ID",
        description="HTTP header name for correlation/request ID (default: X-Request-ID)",
    )

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        """Validate service name is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("service_name cannot be empty or whitespace")
        return v.strip()
    business_events: Optional[Dict[str, BusinessEventConfig]] = Field(
        default=None,
        description="Map of endpoint patterns to business event configurations for analytics tracking"
    )
    payload_size_limit: int = Field(
        default=10_240,
        description="Maximum size in bytes for logged request/response bodies (default 10KB)",
    )
    additional_redaction_patterns: Optional[list[str]] = Field(
        default=None,
        description="Additional field name patterns to redact beyond defaults",
    )
    log_request_headers: bool = Field(
        default=True, description="Whether to log request headers (redacted)"
    )
    log_response_headers: bool = Field(
        default=False, description="Whether to log response headers (redacted)"
    )
    log_query_params: bool = Field(default=True, description="Whether to log query parameters")
    log_request_body: bool = Field(
        default=True,
        description="Whether to log request bodies for the application"
    )
    log_response_body: bool = Field(
        default=True,
        description="Whether to log response bodies for the application"
    )
    excluded_paths: Optional[Union[List[str], Dict[str, List[str]]]] = Field(
        default=None,
        description=(
            "Paths to exclude from observability middleware. "
            "Can be a list of path patterns (e.g., ['/health', '/metrics', '/stream*']) "
            "or a dict mapping HTTP methods to paths (e.g., {'GET': ['/health'], 'POST': ['/stream*']}). "
            "Supports wildcards (*) for pattern matching."
        )
    )
    exception_mappings: Optional[List[ExceptionMapping]] = Field(
        default=None,
        description=(
            "Ordered exception→response mappings handled at the middleware layer. "
            "First isinstance match wins; unmatched exceptions are logged as errors "
            "and re-raised as before. Not applied on excluded_paths unless "
            "map_exceptions_on_excluded_paths is True."
        ),
    )
    map_exceptions_on_excluded_paths: bool = Field(
        default=False,
        description=(
            "When True, exception_mappings also apply on excluded_paths: a mapped "
            "failure returns its configured response and logs one minimal line. "
            "Default False keeps excluded paths fully bypassed (no logs, exceptions "
            "propagate untouched)."
        ),
    )
