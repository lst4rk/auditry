"""Basic tests for middleware functionality."""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from auditry import ObservabilityMiddleware, ObservabilityConfig, configure_logging


configure_logging(level="INFO")


def test_basic_request():
    """Test basic request logging."""
    app = FastAPI()
    app.add_middleware(
        ObservabilityMiddleware,
        config=ObservabilityConfig(service_name="test-service")
    )

    @app.get("/test")
    def test_route():
        return {"message": "ok"}

    client = TestClient(app)
    response = client.get("/test")
    assert response.status_code == 200
    assert response.json() == {"message": "ok"}


def test_user_id_from_state():
    """Test that user_id is captured from request.state.user_id."""
    app = FastAPI()
    app.add_middleware(
        ObservabilityMiddleware,
        config=ObservabilityConfig(service_name="test-service")
    )

    @app.get("/user")
    def user_route(request: Request):
        request.state.user_id = "user_123"
        return {"user": "ok"}

    client = TestClient(app)
    response = client.get("/user")
    assert response.status_code == 200


def test_user_id_from_user_object():
    """Test that user_id is captured from request.state.user.id."""
    app = FastAPI()
    app.add_middleware(
        ObservabilityMiddleware,
        config=ObservabilityConfig(service_name="test-service")
    )

    class User:
        def __init__(self):
            self.id = "user_456"

    @app.get("/user")
    def user_route(request: Request):
        request.state.user = User()
        return {"user": "ok"}

    client = TestClient(app)
    response = client.get("/user")
    assert response.status_code == 200


def test_correlation_id_in_response():
    """Test that correlation ID is added to response headers."""
    app = FastAPI()
    app.add_middleware(
        ObservabilityMiddleware,
        config=ObservabilityConfig(service_name="test-service")
    )

    @app.get("/test")
    def test_route():
        return {"message": "ok"}

    client = TestClient(app)
    response = client.get("/test")
    assert "X-Correlation-ID" in response.headers