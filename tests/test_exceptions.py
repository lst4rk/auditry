"""Tests for the standardized exception handler factory."""

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auditry import ObservabilityConfig, configure_logging
from auditry.fastapi import create_middleware
from auditry.fastapi.exceptions import (
    BaseAPIException,
    ErrorResponse,
    create_exception_handler,
)

configure_logging(level="INFO")


class CustomDomainError(Exception):
    pass


class TokenExpiredError(Exception):
    pass


@pytest.fixture
def app_with_handler():
    """Create a FastAPI app with the standardized exception handler."""
    app = FastAPI()
    app = create_middleware(app, config=ObservabilityConfig(service_name="test-svc"))

    handler = create_exception_handler(
        exception_mapping={
            TokenExpiredError: (401, "auth.token_expired", "auth", False),
            CustomDomainError: (400, "domain.bad_input", "validation", False),
        },
    )
    app.add_exception_handler(Exception, handler)

    @app.get("/ok")
    def ok_route():
        return {"status": "ok"}

    @app.get("/domain-error")
    def domain_error_route():
        raise CustomDomainError("bad input")

    @app.get("/token-expired")
    def token_expired_route():
        raise TokenExpiredError("token is expired")

    @app.get("/unhandled")
    def unhandled_route():
        raise RuntimeError("something broke")

    @app.get("/base-api-error")
    def base_api_error_route():
        raise BaseAPIException(detail="not found", status_code=404, error_type="NotFound")

    @app.get("/http-exception")
    def http_exception_route():
        raise HTTPException(status_code=403, detail="forbidden")

    return app


def test_create_exception_handler_custom_mapping_domain_error(app_with_handler):
    client = TestClient(app_with_handler, raise_server_exceptions=False)

    response = client.get("/domain-error")

    assert response.status_code == 400
    body = response.json()
    assert body["detail"] == "bad input"
    assert body["error"]["code"] == "domain.bad_input"
    assert body["error"]["message"] == "bad input"
    assert body["error"]["category"] == "validation"
    assert body["error"]["context"]["path"] == "/domain-error"
    assert body["error"]["context"]["status_code"] == 400


def test_create_exception_handler_custom_mapping_token_expired(app_with_handler):
    client = TestClient(app_with_handler, raise_server_exceptions=False)

    response = client.get("/token-expired")

    assert response.status_code == 401
    body = response.json()
    assert body["detail"] == "token is expired"
    assert body["error"]["code"] == "auth.token_expired"
    assert body["error"]["category"] == "auth"


def test_create_exception_handler_unmapped_exception_returns_500(app_with_handler):
    client = TestClient(app_with_handler, raise_server_exceptions=False)

    response = client.get("/unhandled")

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "something broke"
    assert body["error"]["code"] == "internal.unhandled_exception"
    assert body["error"]["category"] == "internal"


def test_create_exception_handler_base_api_exception(app_with_handler):
    client = TestClient(app_with_handler, raise_server_exceptions=False)

    response = client.get("/base-api-error")

    assert response.status_code == 404
    body = response.json()
    assert body["detail"] == "not found"
    assert body["error"]["code"] == "NotFound"
    assert body["error"]["category"] == "not_found"


def test_create_exception_handler_http_exception_is_reraised(app_with_handler):
    client = TestClient(app_with_handler, raise_server_exceptions=False)

    response = client.get("/http-exception")

    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden"


def test_create_exception_handler_includes_request_id(app_with_handler):
    client = TestClient(app_with_handler, raise_server_exceptions=False)

    response = client.get("/domain-error")

    body = response.json()
    assert "request_id" in body["error"]["context"]


def test_create_exception_handler_default_mapping():
    app = FastAPI()
    app = create_middleware(app, config=ObservabilityConfig(service_name="test-svc"))

    handler = create_exception_handler()
    app.add_exception_handler(Exception, handler)

    @app.get("/fail")
    def fail_route():
        raise ValueError("oops")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/fail")

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "oops"
    assert body["error"]["code"] == "internal.unhandled_exception"


def test_create_exception_handler_traceback_included_in_dev_env():
    app = FastAPI()
    app = create_middleware(app, config=ObservabilityConfig(service_name="test-svc"))

    handler = create_exception_handler(include_traceback_in=["local", "dev"])
    app.add_exception_handler(Exception, handler)

    @app.get("/fail")
    def fail_route():
        raise ValueError("oops")

    client = TestClient(app, raise_server_exceptions=False)

    with patch.dict(os.environ, {"ENV": "local"}):
        response = client.get("/fail")

    body = response.json()
    assert "traceback" in body["error"]["context"]
    assert "ValueError" in body["error"]["context"]["traceback"]


def test_create_exception_handler_traceback_excluded_in_prod():
    app = FastAPI()
    app = create_middleware(app, config=ObservabilityConfig(service_name="test-svc"))

    handler = create_exception_handler(include_traceback_in=["local", "dev"])
    app.add_exception_handler(Exception, handler)

    @app.get("/fail")
    def fail_route():
        raise ValueError("oops")

    client = TestClient(app, raise_server_exceptions=False)

    with patch.dict(os.environ, {"ENV": "prod"}):
        response = client.get("/fail")

    body = response.json()
    assert "traceback" not in body["error"]["context"]


def test_error_response_model_fields():
    resp = ErrorResponse(
        detail="test message",
        error={
            "code": "test.error",
            "message": "test message",
            "category": "validation",
            "context": {"request_id": "req-123", "path": "/test", "status_code": 422},
            "retryable": False,
        },
    )

    assert resp.detail == "test message"
    assert resp.error.code == "test.error"
    assert resp.error.message == "test message"
    assert resp.error.context["request_id"] == "req-123"
    assert resp.error.context["path"] == "/test"
    assert resp.error.context["status_code"] == 422


def test_base_api_exception_attributes():
    exc = BaseAPIException(
        detail="bad",
        status_code=422,
        error_type="validation.request_invalid",
        category="validation",
        context={"field": "name"},
        retryable=False,
    )

    assert exc.detail == "bad"
    assert exc.status_code == 422
    assert exc.error_type == "validation.request_invalid"
    assert exc.category == "validation"
    assert exc.context["field"] == "name"
    assert exc.retryable is False
    assert str(exc) == "bad"


def test_base_api_exception_defaults():
    exc = BaseAPIException(detail="fail")

    assert exc.status_code == 500
    assert exc.error_type == "internal.unhandled_exception"
    assert exc.category == "internal"
    assert exc.context == {}
    assert exc.retryable is False
