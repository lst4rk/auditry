"""Basic tests for correlation ID functionality."""
from auditry.correlation import get_correlation_id


def test_get_correlation_id_returns_none_when_not_set():
    """Test that get_correlation_id returns None when no correlation ID is set."""
    # Outside of request context, should return None
    result = get_correlation_id()
    assert result is None