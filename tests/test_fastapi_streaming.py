"""Tests for FastAPI streaming response handling."""

import asyncio
import json
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from src.auditry import ObservabilityConfig
from src.auditry.fastapi import create_middleware


@pytest.fixture
def app():
    """Create a FastAPI app with auditry middleware."""
    app = FastAPI()

    # Configure auditry
    config = ObservabilityConfig(
        service_name="test-fastapi-streaming",
    )

    # Apply auditry middleware
    app = create_middleware(app, config)

    @app.get("/stream")
    async def streaming_endpoint():
        """Endpoint that returns streaming response."""
        async def generate():
            for i in range(3):
                yield f"data: chunk {i}\n\n"
                await asyncio.sleep(0.01)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.get("/regular")
    async def regular_endpoint():
        """Endpoint that returns regular JSON response."""
        return {"message": "Regular response", "data": [1, 2, 3]}

    @app.get("/large")
    async def large_endpoint():
        """Endpoint that returns large JSON response."""
        return {"data": list(range(1000))}

    @app.get("/sync-stream")
    def sync_streaming_endpoint():
        """Endpoint that returns synchronous streaming response."""
        def generate():
            for i in range(3):
                yield f"data: sync chunk {i}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    return app


@pytest.fixture
def app_without_middleware():
    """Create a FastAPI app without auditry middleware."""
    app = FastAPI()

    @app.get("/stream")
    async def streaming_endpoint():
        """Endpoint that returns streaming response."""
        async def generate():
            for i in range(3):
                yield f"data: chunk {i}\n\n"
                await asyncio.sleep(0.01)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.get("/regular")
    async def regular_endpoint():
        """Endpoint that returns regular JSON response."""
        return {"message": "Regular response", "data": [1, 2, 3]}

    return app


@pytest.fixture
def client(app):
    """Create a test client for the app with middleware."""
    return TestClient(app)


@pytest.fixture
def client_without_middleware(app_without_middleware):
    """Create a test client for the app without middleware."""
    return TestClient(app_without_middleware)


def test_streaming_response_with_middleware(client, caplog):
    """Test that streaming responses work correctly with auditry middleware."""
    # Test streaming endpoint
    response = client.get("/stream")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    # Read the streaming content
    content = response.text
    assert "data: chunk 0" in content
    assert "data: chunk 1" in content
    assert "data: chunk 2" in content

    # The streaming response should have been logged with body=None
    # Logs are printed to stdout by auditry's logger

    # Verify correlation header is set
    assert "X-Correlation-Id" in response.headers


def test_regular_response_with_middleware(client, caplog):
    """Test that regular responses work correctly with auditry middleware."""
    # Test regular endpoint
    response = client.get("/regular")
    assert response.status_code == 200

    data = response.json()
    assert data == {"message": "Regular response", "data": [1, 2, 3]}

    # The regular response should have been logged with full body
    # Logs are printed to stdout by auditry's logger

    # Verify correlation header is set
    assert "X-Correlation-Id" in response.headers


def test_streaming_without_middleware(client_without_middleware):
    """Test that streaming works without middleware (baseline test)."""
    # Test streaming endpoint
    response = client_without_middleware.get("/stream")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    # Read the streaming content
    content = response.text
    assert "data: chunk 0" in content
    assert "data: chunk 1" in content
    assert "data: chunk 2" in content

    # No correlation header without middleware
    assert "X-Correlation-Id" not in response.headers


def test_large_response_with_middleware(client):
    """Test that large non-streaming responses are handled correctly."""
    # Test large response endpoint
    response = client.get("/large")
    assert response.status_code == 200

    data = response.json()
    assert "data" in data
    assert len(data["data"]) == 1000
    assert data["data"][0] == 0
    assert data["data"][999] == 999

    # Verify correlation header is set
    assert "X-Correlation-Id" in response.headers


def test_sync_streaming_response_with_middleware(client):
    """Test that synchronous streaming responses work correctly."""
    # Test sync streaming endpoint
    response = client.get("/sync-stream")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    # Read the streaming content
    content = response.text
    assert "data: sync chunk 0" in content
    assert "data: sync chunk 1" in content
    assert "data: sync chunk 2" in content

    # Verify correlation header is set
    assert "X-Correlation-Id" in response.headers


def test_multiple_requests_sequential(client):
    """Test multiple sequential requests with mixed types."""
    # Make multiple requests sequentially
    responses = []

    # Streaming request
    responses.append(client.get("/stream"))
    # Regular request
    responses.append(client.get("/regular"))
    # Another streaming request
    responses.append(client.get("/stream"))
    # Large request
    responses.append(client.get("/large"))

    # Verify all responses
    assert responses[0].status_code == 200
    assert "data: chunk 0" in responses[0].text

    assert responses[1].status_code == 200
    assert responses[1].json()["message"] == "Regular response"

    assert responses[2].status_code == 200
    assert "data: chunk 0" in responses[2].text

    assert responses[3].status_code == 200
    assert len(responses[3].json()["data"]) == 1000


def test_streaming_with_different_media_types(app):
    """Test streaming with different media types."""
    # Add an endpoint with different media type
    @app.get("/json-stream")
    async def json_streaming_endpoint():
        """Endpoint that returns streaming JSON."""
        async def generate():
            for i in range(3):
                yield json.dumps({"chunk": i}) + "\n"
                await asyncio.sleep(0.01)

        return StreamingResponse(generate(), media_type="application/json")

    client = TestClient(app)

    # Test JSON streaming endpoint
    response = client.get("/json-stream")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]

    # Parse the streaming JSON
    lines = response.text.strip().split("\n")
    assert len(lines) == 3

    for i, line in enumerate(lines):
        data = json.loads(line)
        assert data["chunk"] == i

    # Verify correlation header is set
    assert "X-Correlation-Id" in response.headers


def test_error_in_streaming_response(app):
    """Test that errors in streaming responses are handled correctly."""
    @app.get("/error-stream")
    async def error_streaming_endpoint():
        """Endpoint that raises an error during streaming."""
        async def generate():
            yield f"data: chunk 0\n\n"
            await asyncio.sleep(0.01)
            raise ValueError("Streaming error")

        return StreamingResponse(generate(), media_type="text/event-stream")

    client = TestClient(app)

    # The TestClient will handle the error differently than a real server
    # In a real scenario, the connection would be closed
    with pytest.raises(ValueError):
        response = client.get("/error-stream")
        # Force reading all content to trigger the error
        _ = response.text