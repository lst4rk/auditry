"""Standardized error handling for FastAPI services."""

import traceback
from typing import Callable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..correlation import get_correlation_id


class ErrorResponse(BaseModel):
    """Standard error response model for all Farsight services."""
    error_type: str
    message: str
    request_id: Optional[str] = None
    path: str
    status_code: int


class BaseAPIException(Exception):
    """Base exception for API errors. Services can subclass this."""
    def __init__(self, detail: str, status_code: int = 500, error_type: str = "InternalServerError"):
        self.detail = detail
        self.status_code = status_code
        self.error_type = error_type
        super().__init__(detail)


def create_exception_handler(
    exception_mapping: Optional[dict[type[Exception], tuple]] = None,
    include_traceback_in: Optional[list[str]] = None,
) -> Callable:
    """
    Factory that creates a standardized exception handler for FastAPI.

    Args:
        exception_mapping: Optional dict mapping exception types to (status_code, error_type) tuples.
            Example: {TokenExpiredException: (401, "AuthenticationError"), DomainException: (400, "DomainError")}
        include_traceback_in: Optional list of environment prefixes where traceback should be included
            in the response (e.g., ["local", "dev"]). If None, traceback is never included.

    Returns:
        An async exception handler function compatible with FastAPI's add_exception_handler.
    """
    mapping = exception_mapping or {}

    async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            raise exc

        if isinstance(exc, BaseAPIException):
            status_code = exc.status_code
            error_type = exc.error_type
            message = exc.detail
        else:
            # Check custom mapping
            status_code = 500
            error_type = "InternalServerError"
            message = str(exc)
            for exc_type, (code, etype) in mapping.items():
                if isinstance(exc, exc_type):
                    status_code = code
                    error_type = etype
                    break

        request_id = get_correlation_id()

        error_response = ErrorResponse(
            error_type=error_type,
            message=message,
            request_id=request_id,
            path=str(request.url.path),
            status_code=status_code,
        )

        content = error_response.model_dump()

        # Optionally include traceback for dev environments
        if include_traceback_in:
            import os
            env_stage = os.getenv("ENV", "local")
            if any(env_stage.startswith(prefix) for prefix in include_traceback_in):
                content["traceback"] = traceback.format_exc()

        return JSONResponse(status_code=status_code, content=content)

    return exception_handler
