from typing import Optional, Dict, List
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
        default="X-Correlation-ID",
        description="HTTP header name for correlation ID (default: X-Correlation-ID)",
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