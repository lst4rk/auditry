"""Sentry integration helpers for standardized distributed tracing."""

from typing import Optional


def configure_sentry(
    dsn: Optional[str],
    environment: str,
    traces_sample_rate: float = 0.2,
    send_default_pii: bool = True,
    **kwargs,
) -> None:
    """
    Configure Sentry with distributed tracing enabled.

    This wraps sentry_sdk.init() with tracing configuration and
    attaches the request ID as a Sentry tag on every event.

    Args:
        dsn: Sentry DSN. If None/empty, Sentry is not initialized.
        environment: Environment name (e.g., "local", "dev", "prod").
        traces_sample_rate: Sample rate for performance tracing (0.0 to 1.0).
        send_default_pii: Whether to send PII data.
        **kwargs: Additional arguments passed to sentry_sdk.init().
    """
    if not dsn:
        return

    import sentry_sdk

    from .correlation import get_correlation_id

    def before_send(event, hint):
        """Attach request_id to every Sentry event."""
        request_id = get_correlation_id()
        if request_id:
            event.setdefault("tags", {})["request_id"] = request_id
        return event

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        send_default_pii=send_default_pii,
        traces_sample_rate=traces_sample_rate,
        enable_tracing=True,
        before_send=before_send,
        **kwargs,
    )
