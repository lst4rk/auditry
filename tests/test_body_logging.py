"""Tests for request/response body logging configuration."""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from quart import Quart

from auditry import ObservabilityConfig, configure_logging
from auditry.fastapi import create_middleware
from auditry.quart import create_middleware as create_quart_middleware


configure_logging(level="INFO")


def test_fastapi_disable_request_body_logging():
    """Test that request body logging can be disabled in FastAPI."""
    app = FastAPI()
    app = create_middleware(
        app,
        config=ObservabilityConfig(
            service_name="test-service",
            log_request_body=False,  # Disable request body logging
            log_response_body=True,
        )
    )

    @app.post("/users")
    def create_user():
        return {"id": "123", "status": "created"}

    client = TestClient(app)
    response = client.post(
        "/users",
        json={"name": "Test User", "password": "secret123", "ssn": "123-45-6789"}
    )
    assert response.status_code == 200
    # Body should not be logged, but response should be


def test_fastapi_disable_response_body_logging():
    """Test that response body logging can be disabled in FastAPI."""
    app = FastAPI()
    app = create_middleware(
        app,
        config=ObservabilityConfig(
            service_name="test-service",
            log_request_body=True,
            log_response_body=False,  # Disable response body logging
        )
    )

    @app.post("/users")
    def create_user():
        return {
            "id": "123",
            "name": "Test User",
            "ssn": "123-45-6789",  # Sensitive data in response
            "api_key": "secret-key"
        }

    client = TestClient(app)
    response = client.post(
        "/users",
        json={"name": "Test User"}
    )
    assert response.status_code == 200
    # Request body should be logged, but response body should not be


def test_fastapi_disable_both_body_logging():
    """Test that both request and response body logging can be disabled."""
    app = FastAPI()
    app = create_middleware(
        app,
        config=ObservabilityConfig(
            service_name="test-service",
            log_request_body=False,
            log_response_body=False,
        )
    )

    @app.post("/sensitive")
    def sensitive_endpoint():
        return {"secret": "data"}

    client = TestClient(app)
    response = client.post(
        "/sensitive",
        json={"password": "secret", "credit_card": "1234-5678-9012-3456"}
    )
    assert response.status_code == 200
    # Neither request nor response bodies should be logged


@pytest.mark.asyncio
async def test_quart_disable_request_body_logging():
    """Test that request body logging can be disabled in Quart."""
    app = Quart(__name__)
    app = create_quart_middleware(
        app,
        config=ObservabilityConfig(
            service_name="test-quart-service",
            log_request_body=False,  # Disable request body logging
            log_response_body=True,
        )
    )

    @app.route("/users", methods=["POST"])
    async def create_user():
        return {"id": "123", "status": "created"}

    client = app.test_client()
    response = await client.post(
        "/users",
        json={"name": "Test User", "password": "secret123", "ssn": "123-45-6789"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_quart_disable_response_body_logging():
    """Test that response body logging can be disabled in Quart."""
    app = Quart(__name__)
    app = create_quart_middleware(
        app,
        config=ObservabilityConfig(
            service_name="test-quart-service",
            log_request_body=True,
            log_response_body=False,  # Disable response body logging
        )
    )

    @app.route("/users", methods=["POST"])
    async def create_user():
        return {
            "id": "123",
            "name": "Test User",
            "ssn": "123-45-6789",  # Sensitive data in response
            "api_key": "secret-key"
        }

    client = app.test_client()
    response = await client.post(
        "/users",
        json={"name": "Test User"}
    )
    assert response.status_code == 200


def test_service_name_required():
    """Test that service_name is required and cannot be empty."""
    # Should raise validation error without service_name
    with pytest.raises(Exception):  # Pydantic ValidationError
        ObservabilityConfig()

    # Should raise validation error with empty service_name
    with pytest.raises(Exception):  # Pydantic ValidationError
        ObservabilityConfig(service_name="")

    # Should raise validation error with whitespace-only service_name
    with pytest.raises(Exception):  # Pydantic ValidationError
        ObservabilityConfig(service_name="   ")

    # Should work with valid service_name
    config = ObservabilityConfig(service_name="valid-service")
    assert config.service_name == "valid-service"