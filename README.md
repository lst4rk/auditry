# auditry

A clean, framework-agnostic observability middleware for FastAPI and Quart that provides comprehensive request/response logging, correlation ID tracking, business event extraction, and sensitive data redaction.

[![PyPI version](https://badge.fury.io/py/auditry.svg)](https://badge.fury.io/py/auditry)
[![Python Versions](https://img.shields.io/pypi/pyversions/auditry.svg)](https://pypi.org/project/auditry/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Installation

### For FastAPI

```bash
pip install auditry[fastapi]
```

### For Quart

```bash
pip install auditry[quart]
```

### For both frameworks

```bash
pip install auditry[all]
```

## Quick Start

### FastAPI

```python
from fastapi import FastAPI
from auditry import configure_logging, ObservabilityConfig, get_logger
from auditry.fastapi import create_middleware

# Configure structured logging at startup
configure_logging(level="INFO")

app = FastAPI()

# Add observability middleware (single line!)
app = create_middleware(
    app,
    config=ObservabilityConfig(service_name="my-service")
)

logger = get_logger(__name__)

@app.get("/")
async def root():
    logger.info("Hello World")
    return {"message": "Hello World"}
```

### Quart

```python
from quart import Quart
from auditry import configure_logging, ObservabilityConfig, get_logger
from auditry.quart import create_middleware

# Configure structured logging at startup
configure_logging(level="INFO")

app = Quart(__name__)

# Add observability middleware (single line!)
app = create_middleware(
    app,
    config=ObservabilityConfig(service_name="my-service")
)

logger = get_logger(__name__)

@app.route("/")
async def root():
    logger.info("Hello World")
    return {"message": "Hello World"}
```

## Configuration

### Required Configuration

```python
config = ObservabilityConfig(
    service_name="your-service-name",  # REQUIRED
)
```

**Note:** The `service_name` is required and must be provided. This ensures all services have meaningful names in logs rather than generic defaults.

### Full Configuration Options

```python
config = ObservabilityConfig(
    # REQUIRED: Service name for log filtering (no default)
    service_name="my-service-name",

    # Correlation ID header name (default: X-Correlation-ID)
    # Use this if your org uses a different header, such as X-Request-ID
    correlation_id_header="X-Correlation-ID",

    # Maximum request/response body size to log (default: 10KB)
    payload_size_limit=10_240,

    # Additional sensitive field patterns to redact
    additional_redaction_patterns=["internal_id", "employee_ssn"],

    # Whether to log request headers (default: True)
    log_request_headers=True,

    # Whether to log response headers (default: False)
    log_response_headers=False,

    # Whether to log query parameters (default: True)
    log_query_params=True,

    # Whether to log request bodies for all endpoints (default: True)
    # Set to False for applications handling sensitive data
    log_request_body=True,

    # Whether to log response bodies for all endpoints (default: True)
    # Set to False for applications returning sensitive data
    log_response_body=True,
)

# For FastAPI:
from auditry.fastapi import create_middleware
app = create_middleware(app, config)

# For Quart:
from auditry.quart import create_middleware
app = create_middleware(app, config)
```

## Correlation IDs

Correlation IDs are automatically handled:

- **Incoming requests**: Extracts from `X-Correlation-ID` header (or your custom header)
- **Generated if missing**: Creates a new UUID if no correlation ID provided
- **Added to response**: Returns the correlation ID in the response header
- **Included in logs**: Automatically included in all structured logs

### Using Correlation IDs in Your Code

```python
from auditry import get_logger, get_correlation_id

logger = get_logger(__name__)

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    # Correlation ID is automatically available
    correlation_id = get_correlation_id()

    # All logs automatically include the correlation ID
    logger.info(f"Fetching user {user_id}")

    return {"user_id": user_id, "correlation_id": correlation_id}
```

### Propagating to Downstream Services

```python
import httpx
from auditry import get_correlation_id

@app.get("/proxy")
async def proxy_request():
    # Get the current correlation ID
    correlation_id = get_correlation_id()

    # Pass it to downstream services
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://downstream-service.com/api/data",
            headers={"X-Correlation-ID": correlation_id}  # Use your org's header name
        )

    return response.json()
```

## User Tracking

The middleware automatically extracts user IDs from your authentication system and includes them in logs.

### FastAPI User Tracking

```python
from fastapi import Request, Depends

async def get_current_user(request: Request):
    # Your authentication logic here
    user_id = "user-123"

    # Set user_id in request state for auditry to capture
    request.state.user_id = user_id
    # OR if you have a user object:
    # request.state.user = user_object  # Must have .id or .user_id attribute

    return user_id

@app.get("/protected")
async def protected_route(user_id: str = Depends(get_current_user)):
    return {"message": "Protected content"}
```

### Quart User Tracking

```python
from quart import request

@app.before_request
async def authenticate():
    # Your authentication logic here

    # Set user on request for auditry to capture
    request.current_user = AuthenticatedUser(id="user-123")
    # OR use g.user or g.user_id
    # from quart import g
    # g.user_id = "user-123"
```

The middleware automatically finds the user ID from these locations:
- **FastAPI**: `request.state.user_id` or `request.state.user.id`
- **Quart**: `request.current_user.id`, `g.user.id`, or `g.user_id`

## Business Event Tagging (For Analytics)

Tag specific endpoints as "business events" to make analytics queries easier for your sales/product teams.

### Configuration

Tag endpoints in your middleware config - zero code changes needed in your actual endpoints:

```python
from auditry import ObservabilityConfig, BusinessEventConfig

config = ObservabilityConfig(
    service_name="my-service-name",

    # Define which endpoints to tag for analytics
    business_events={
        "POST /workflows": BusinessEventConfig(
            event_type="workflow.created",
            extract_from_request=["file_id"],  # Pull file_id from request body
            extract_from_response=["id"],       # Pull workflow id from response
        ),
        "DELETE /workflows/{workflow_id}": BusinessEventConfig(
            event_type="workflow.deleted",
            extract_from_path=["workflow_id"],    # Pull workflow_id from URL path
        ),
    },
)

# Apply to your framework
from auditry.fastapi import create_middleware  # or auditry.quart
app = create_middleware(app, config)
```

### Log Output with Event Tags

Regular log (no tagging):
```json
{
  "service": "my-service-name",
  "message": "Request completed: POST /workflows - Status: 201",
  "request": {...},
  "response": {...}
}
```

Tagged business event log:
```json
{
  "service": "my-service-name",
  "message": "Request completed: POST /workflows - Status: 201",
  "event_type": "workflow.created",          // ← Filterable in log platform
  "business_context": {
    "file_id": "file_123",                   // ← From request body
    "id": "workflow_789"                    // ← From response body
  },
  "request": {...},
  "response": {...}
}
```

### Supported Extract Locations

- `extract_from_request`: Fields from request JSON body
- `extract_from_response`: Fields from response JSON body  
- `extract_from_path`: Parameters from URL path (e.g., `/workflows/{workflow_id}`)

## Log Output

All logs are structured JSON, ready for log aggregators:

```json
{
  "timestamp": "2025-10-28T12:34:56.789012+00:00",
  "level": "INFO",
  "service": "my-service-name",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Request completed: POST /workflows - Status: 201 - Duration: 45.23ms",
  "request": {
    "method": "POST",
    "path": "/workflows",
    "query_params": {},
    "headers": {"user-agent": "curl/7.64.1", "authorization": "[REDACTED]"},
    "body": {"name": "My Workflow", "password": "[REDACTED]"},
    "user_id": "user_12345"
  },
  "response": {
    "status_code": 201,
    "duration_ms": 45.23,
    "body": {"id": "workflow_789", "name": "My Workflow"}
  }
}
```

## Sensitive Data Handling

### Automatic Redaction

Automatically redacts these sensitive field patterns in all logged requests/responses:

- `password`
- `token`
- `api_key` / `apikey`
- `secret`
- `authorization`
- `ssn` / `social_security_number`
- `credit_card` / `creditcard`
- `x-api-key`

Add custom patterns via configuration:

```python
config = ObservabilityConfig(
    service_name="my-service-name",
    additional_redaction_patterns=["internal_token", "employee_id"],
)
```

### Disabling Body Logging (Application-Wide)

For applications handling sensitive data, you can disable logging of request and/or response bodies across the entire application:

```python
config = ObservabilityConfig(
    service_name="my-service-name",

    # Disable request body logging for all endpoints
    log_request_body=False,

    # Disable response body logging for all endpoints
    log_response_body=False,
)
```

When body logging is disabled, logs will show `[BODY_LOGGING_DISABLED]` instead of the actual content, while still logging metadata like headers, status codes, and timing information.

### Excluding Paths from Middleware

You can exclude specific paths from observability middleware processing, which is useful for:
- Health check endpoints that don't need logging
- Streaming endpoints that might be disrupted by middleware
- Internal/admin endpoints with different logging requirements
- High-frequency endpoints where logging adds too much overhead

#### Simple Path Exclusion

Exclude paths for all HTTP methods:

```python
config = ObservabilityConfig(
    service_name="my-service-name",
    excluded_paths=[
        '/health',           # Exact match
        '/metrics',          # Exact match
        '/stream*',          # Wildcard - matches /stream, /streaming, /stream/events
        '/api/*/internal',   # Wildcard - matches /api/v1/internal, /api/v2/internal
        '/admin/',           # Prefix - matches /admin/* (trailing slash indicates prefix)
    ],
)
```

#### Method-Specific Path Exclusion

Exclude paths for specific HTTP methods:

```python
config = ObservabilityConfig(
    service_name="my-service-name",
    excluded_paths={
        'GET': ['/health', '/metrics'],    # Only exclude GET requests
        'POST': ['/webhook/*'],             # Only exclude POST requests
        '*': ['/admin/*'],                  # Exclude all methods
    },
)
```

#### Example: Excluding Streaming Endpoints in Quart

For Quart applications with streaming endpoints that are disrupted by middleware:

```python
from quart import Quart, Response, stream_with_context
from auditry import ObservabilityConfig
from auditry.quart import create_middleware

app = Quart(__name__)

# Exclude all streaming endpoints
config = ObservabilityConfig(
    service_name="streaming-service",
    excluded_paths=['/stream/*', '/events', '/live/*'],
)

app = create_middleware(app, config)

@app.route('/stream/data')
async def stream_data():
    """This endpoint will bypass observability middleware."""
    @stream_with_context
    async def generate():
        for i in range(100):
            yield f"data: {i}\n\n"
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/users')
async def get_users():
    """This endpoint will still be logged normally."""
    return {"users": ["user1", "user2"]}
```

**Note:** Excluded paths still receive correlation IDs for request tracing, but no request/response logging occurs.

## Best Practices

### 1. Configure Logging Early

Call `configure_logging()` at application startup, before any other code:

```python
from auditry import configure_logging

# First thing in your app
configure_logging(level="INFO")

app = FastAPI()
# ... rest of your app
```

### 2. Use Structured Logging

Always use `get_logger(__name__)` instead of standard Python logging:

```python
from auditry import get_logger

logger = get_logger(__name__)

# Good - structured with correlation ID
logger.info("Processing payment", amount=100.50, currency="USD")

# Bad - loses structured data
import logging
logging.info("Processing payment")
```

### 3. Propagate Correlation IDs

When calling downstream services, always pass the correlation ID:

```python
from auditry import get_correlation_id

correlation_id = get_correlation_id()
headers = {"X-Correlation-ID": correlation_id}  # Use your org's header name
response = await client.get(url, headers=headers)
```

### 4. Customize for Your Organization

Match your org's conventions:

```python
config = ObservabilityConfig(
    service_name="my-service-name",
    correlation_id_header="X-Request-ID",  # If your org uses this header instead
    additional_redaction_patterns=["ssn", "tax_id"],  # Your sensitive fields
)
```

## Example Output: Success vs Failure

### Successful Request

```json
{
  "level": "INFO",
  "service": "my-service-name",
  "correlation_id": "abc-123",
  "message": "Request completed: POST /workflows - Status: 201 - Duration: 45ms",
  "request": {...},
  "response": {...}
}
```

### Failed Request

```json
{
  "level": "ERROR",
  "service": "my-service-name",
  "correlation_id": "abc-123",
  "message": "Request failed: POST /workflows - Error: ValueError: Invalid name",
  "request": {...},
  "exception_type": "ValueError",
  "exception_message": "Invalid name",
  "execution_duration_ms": 12.34
}
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

Contributions welcome! Please submit a Pull Request.

## Support

For issues and questions: [GitHub Issues](https://github.com/lst4rk/auditry/issues)

## Author

**Liv Stark** - [livstark.work@gmail.com](mailto:livstark.work@gmail.com)