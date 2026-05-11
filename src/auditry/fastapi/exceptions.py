"""Standardized error handling for FastAPI services.

The response envelope follows the chat-gateway standard:
{
  "detail": "...",
  "error": {
    "code": "...",
    "message": "...",
    "category": "...",
    "context": {...},
    "retryable": false
  }
}
"""

import traceback
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..correlation import get_correlation_id


class ErrorDetails(BaseModel):
    """Structured error payload modeled after chat-gateway's AppError envelope."""

    code: str
    message: str
    category: str
    context: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class ErrorResponse(BaseModel):
    """Standard error envelope for all Farsight services."""

    detail: str
    error: ErrorDetails


class BaseAPIException(Exception):
    """Base exception for API errors. Services can subclass this."""

    def __init__(
        self,
        detail: str,
        status_code: int = 500,
        error_type: str = "internal.unhandled_exception",
        *,
        category: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        retryable: bool = False,
    ):
        self.detail = detail
        self.status_code = status_code
        self.error_type = error_type
        self.category = category or _category_from_status(status_code)
        self.context = context or {}
        self.retryable = retryable
        super().__init__(detail)


def _category_from_status(status_code: int) -> str:
    if status_code == 422:
        return "validation"
    if status_code == 404:
        return "not_found"
    if status_code in (401, 403):
        return "auth"
    if status_code == 409:
        return "conflict"
    if status_code == 502:
        return "integration"
    return "internal"


def create_exception_handler(
    exception_mapping: Optional[dict[type[Exception], tuple]] = None,
    include_traceback_in: Optional[list[str]] = None,
) -> Callable:
    """
    Factory that creates a standardized exception handler for FastAPI.

    Args:
        exception_mapping: Optional dict mapping exception types to either:
            - (status_code, error_type) tuples (legacy), or
            - (status_code, error_type, category, retryable) tuples.
            Example:
                {
                    TokenExpiredException: (401, "auth.token_expired", "auth", False),
                    DomainException: (400, "domain.invalid_input"),
                }
        include_traceback_in: Optional list of environment prefixes where traceback should be included
            in the response (e.g., ["local", "dev"]). If None, traceback is never included.

    Returns:
        An async exception handler function compatible with FastAPI's add_exception_handler.
    """
    mapping = exception_mapping or {}

    async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            raise exc

        status_code = 500
        error_code = "internal.unhandled_exception"
        message = str(exc)
        category = "internal"
        retryable = False

        if isinstance(exc, BaseAPIException):
            status_code = exc.status_code
            error_code = exc.error_type
            message = exc.detail
            category = exc.category
            retryable = exc.retryable
            error_context = dict(exc.context)
        else:
            error_context: dict[str, Any] = {}
            # Check custom mapping
            for exc_type, config in mapping.items():
                if isinstance(exc, exc_type):
                    if len(config) == 2:
                        status_code, error_code = config
                        category = _category_from_status(status_code)
                        retryable = False
                    elif len(config) == 4:
                        status_code, error_code, category, retryable = config
                    else:
                        raise ValueError(
                            "exception_mapping values must be (status_code, error_type) "
                            "or (status_code, error_type, category, retryable)"
                        )
                    break

        request_id = get_correlation_id()
        error_context.update({"request_id": request_id, "path": str(request.url.path), "status_code": status_code})

        error_response = ErrorResponse(
            detail=message,
            error=ErrorDetails(
                code=error_code,
                message=message,
                category=category,
                context=error_context,
                retryable=retryable,
            ),
        )

        content = error_response.model_dump()

        # Optionally include traceback for dev environments
        if include_traceback_in:
            import os
            env_stage = os.getenv("ENV", "local")
            if any(env_stage.startswith(prefix) for prefix in include_traceback_in):
                content["error"]["context"]["traceback"] = traceback.format_exc()

        return JSONResponse(status_code=status_code, content=content)

    return exception_handler
