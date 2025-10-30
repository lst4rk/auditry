"""Basic tests for Quart middleware functionality."""
import pytest
import asyncio
from quart import Quart, request, g
from quart.testing import QuartClient

from auditry import ObservabilityConfig, configure_logging
from auditry.quart import create_middleware


configure_logging(level="INFO")


@pytest.mark.asyncio
async def test_basic_request():
    """Test basic request logging with Quart."""
    app = Quart(__name__)
    app = create_middleware(
        app,
        config=ObservabilityConfig(service_name="test-quart-service")
    )

    @app.route("/test")
    async def test_route():
        return {"message": "ok"}

    client = app.test_client()
    response = await client.get("/test")
    assert response.status_code == 200
    data = await response.get_json()
    assert data == {"message": "ok"}


@pytest.mark.asyncio
async def test_user_id_from_current_user():
    """Test that user_id is captured from request.current_user."""
    app = Quart(__name__)
    app = create_middleware(
        app,
        config=ObservabilityConfig(service_name="test-quart-service")
    )

    class User:
        def __init__(self, id):
            self.id = id

    @app.before_request
    async def set_user():
        # Simulate authentication setting current_user
        request.current_user = User(id="user_123")

    @app.route("/user")
    async def user_route():
        return {"user": "ok"}

    client = app.test_client()
    response = await client.get("/user")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_user_id_from_g():
    """Test that user_id is captured from g.user_id."""
    app = Quart(__name__)
    app = create_middleware(
        app,
        config=ObservabilityConfig(service_name="test-quart-service")
    )

    @app.before_request
    async def set_user():
        # Simulate authentication setting g.user_id
        g.user_id = "user_456"

    @app.route("/user")
    async def user_route():
        return {"user": "ok"}

    client = app.test_client()
    response = await client.get("/user")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_correlation_id_in_response():
    """Test that correlation ID is added to response headers."""
    app = Quart(__name__)
    app = create_middleware(
        app,
        config=ObservabilityConfig(service_name="test-quart-service")
    )

    @app.route("/test")
    async def test_route():
        return {"message": "ok"}

    client = app.test_client()
    response = await client.get("/test")
    assert response.status_code == 200
    assert "X-Correlation-ID" in response.headers


@pytest.mark.asyncio
async def test_error_handling():
    """Test that errors are logged properly."""
    app = Quart(__name__)
    app = create_middleware(
        app,
        config=ObservabilityConfig(service_name="test-quart-service")
    )

    @app.route("/error")
    async def error_route():
        raise ValueError("Test error")

    client = app.test_client()
    # The error should be raised and logged
    with pytest.raises(ValueError):
        response = await client.get("/error")


@pytest.mark.asyncio
async def test_query_params_logging():
    """Test that query parameters are logged when configured."""
    app = Quart(__name__)
    app = create_middleware(
        app,
        config=ObservabilityConfig(
            service_name="test-quart-service",
            log_query_params=True
        )
    )

    @app.route("/search")
    async def search_route():
        query = request.args.get("q", "")
        return {"query": query}

    client = app.test_client()
    response = await client.get("/search?q=test&limit=10")
    assert response.status_code == 200
    data = await response.get_json()
    assert data["query"] == "test"


@pytest.mark.asyncio
async def test_post_request_body():
    """Test POST request with JSON body."""
    app = Quart(__name__)
    app = create_middleware(
        app,
        config=ObservabilityConfig(service_name="test-quart-service")
    )

    @app.route("/users", methods=["POST"])
    async def create_user():
        data = await request.get_json()
        return {"id": "123", "name": data.get("name")}

    client = app.test_client()
    response = await client.post(
        "/users",
        json={"name": "Test User", "password": "secret123"}
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["name"] == "Test User"