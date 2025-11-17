"""Basic tests for FastAPI middleware functionality."""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from auditry import ObservabilityConfig, configure_logging
from auditry.fastapi import create_middleware


configure_logging(level="INFO")






def test_correlation_id_in_response():
    """Test that correlation ID is added to response headers."""
    app = FastAPI()
    app = create_middleware(
        app,
        config=ObservabilityConfig(service_name="test-service")
    )

    @app.get("/test")
    def test_route():
        return {"message": "ok"}

    client = TestClient(app)
    response = client.get("/test")
    assert "X-Correlation-ID" in response.headers