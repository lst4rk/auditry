"""Tests for configurable exception→response mapping.

Services configure `ObservabilityConfig.exception_mappings` so known
infrastructure failures (e.g. a DB pool-checkout timeout) become clean,
handled responses at the middleware layer instead of unhandled exceptions —
without registering framework-level exception handlers that bypass auditry.
"""

import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from quart import Quart

from auditry import ExceptionMapping, ObservabilityConfig, configure_logging
from auditry.core import resolve_exception_mapping
from auditry.fastapi import create_middleware as create_fastapi_middleware
from auditry.quart import create_middleware as create_quart_middleware

configure_logging(level="INFO")


SERVICE_UNAVAILABLE_BODY = {
    "error": {
        "code": "service.unavailable",
        "category": "integration",
        "retryable": True,
        "message": "Service temporarily unavailable, please retry",
    }
}


def _config(**overrides) -> ObservabilityConfig:
    return ObservabilityConfig(
        service_name="test-service",
        exception_mappings=[
            ExceptionMapping(
                exception_type=TimeoutError,
                status_code=503,
                body=SERVICE_UNAVAILABLE_BODY,
                log_level="warning",
            )
        ],
        **overrides,
    )


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_invalid_log_level_rejected():
    with pytest.raises(ValidationError):
        ExceptionMapping(exception_type=ValueError, status_code=503, body={}, log_level="loud")


def test_non_exception_type_rejected():
    with pytest.raises(ValidationError):
        ExceptionMapping(exception_type=dict, status_code=503, body={})


# ---------------------------------------------------------------------------
# resolve_exception_mapping
# ---------------------------------------------------------------------------


def test_resolver_matches_subclasses():
    mappings = [ExceptionMapping(exception_type=LookupError, status_code=500, body={})]
    assert resolve_exception_mapping(KeyError("x"), mappings) is mappings[0]


def test_resolver_returns_none_when_unmatched():
    mappings = [ExceptionMapping(exception_type=TimeoutError, status_code=503, body={})]
    assert resolve_exception_mapping(RuntimeError("x"), mappings) is None
    assert resolve_exception_mapping(RuntimeError("x"), None) is None


def test_resolver_unwraps_single_leaf_group_duck_typed():
    """Duck-typed unwrap works even without the 3.11 ExceptionGroup builtin."""

    class FakeGroup(Exception):
        def __init__(self, exceptions):
            self.exceptions = exceptions

    mappings = [ExceptionMapping(exception_type=TimeoutError, status_code=503, body={})]
    nested = FakeGroup([FakeGroup([TimeoutError("pool timeout")])])
    assert resolve_exception_mapping(nested, mappings) is mappings[0]

    # Multi-leaf groups are ambiguous — no unwrap, no match
    multi = FakeGroup([TimeoutError("a"), ValueError("b")])
    assert resolve_exception_mapping(multi, mappings) is None


@pytest.mark.skipif(sys.version_info < (3, 11), reason="ExceptionGroup requires 3.11+")
def test_resolver_unwraps_real_exception_group():
    mappings = [ExceptionMapping(exception_type=TimeoutError, status_code=503, body={})]
    group = ExceptionGroup("wrapped", [TimeoutError("pool timeout")])
    assert resolve_exception_mapping(group, mappings) is mappings[0]


# ---------------------------------------------------------------------------
# FastAPI middleware
# ---------------------------------------------------------------------------


def _fastapi_client(config: ObservabilityConfig) -> TestClient:
    app = FastAPI()
    app = create_fastapi_middleware(app, config=config)

    @app.get("/mapped")
    async def mapped():
        raise TimeoutError("QueuePool limit reached, connection timed out")

    @app.get("/unmapped")
    async def unmapped():
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def test_fastapi_mapped_exception_returns_configured_response():
    response = _fastapi_client(_config()).get("/mapped")

    assert response.status_code == 503
    assert response.json() == SERVICE_UNAVAILABLE_BODY
    assert response.headers["content-type"] == "application/json"
    assert "X-Request-ID" in response.headers


def test_fastapi_unmapped_exception_still_propagates():
    response = _fastapi_client(_config()).get("/unmapped")
    assert response.status_code == 500


def test_fastapi_no_mappings_configured_unchanged():
    config = ObservabilityConfig(service_name="test-service")
    response = _fastapi_client(config).get("/mapped")
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_fastapi_no_mapped_response_after_response_started():
    """If the response already started, the middleware must re-raise, not send."""
    from auditry.fastapi.middleware import FastAPIMiddleware

    async def failing_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise TimeoutError("mid-stream failure")

    middleware = FastAPIMiddleware(failing_app, config=_config())

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/stream",
        "headers": [],
        "query_string": b"",
    }

    with pytest.raises(TimeoutError):
        await middleware(scope, receive, send)

    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 200


# ---------------------------------------------------------------------------
# Quart middleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quart_mapped_exception_returns_configured_response():
    app = Quart(__name__)
    app = create_quart_middleware(app, config=_config())

    @app.route("/mapped")
    async def mapped():
        raise TimeoutError("QueuePool limit reached, connection timed out")

    client = app.test_client()
    response = await client.get("/mapped")

    assert response.status_code == 503
    assert await response.get_json() == SERVICE_UNAVAILABLE_BODY
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_quart_unmapped_exception_still_reraised():
    """Unmatched exceptions keep the existing behavior: logged and re-raised."""
    app = Quart(__name__)
    app = create_quart_middleware(app, config=_config())

    @app.route("/unmapped")
    async def unmapped():
        raise RuntimeError("boom")

    client = app.test_client()
    with pytest.raises(RuntimeError, match="boom"):
        await client.get("/unmapped")
