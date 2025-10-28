"""
Structured logging configuration using structlog.

This module provides JSON-formatted logging that integrates with
correlation IDs and is optimized for log aggregators like Datadog.
"""

import logging
import structlog


def configure_logging(level: str = "INFO") -> None:
    """
    Configure application-wide structured logging using structlog.

    Sets up JSON-formatted logging with timestamps, log levels, and
    correlation IDs. Should be called once at application startup.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Configure structlog processors
    structlog.configure(
        processors=[
            # Add log level to event dict
            structlog.stdlib.add_log_level,
            # Add timestamp in ISO format
            structlog.processors.TimeStamper(fmt="iso"),
            # Add correlation_id from context if available
            structlog.contextvars.merge_contextvars,
            # Format exceptions
            structlog.processors.format_exc_info,
            # Render as JSON
            structlog.processors.JSONRenderer(),
        ],
        # Use standard library logging
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper()),
        force=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog logger instance.

    This logger automatically includes correlation IDs and outputs
    structured JSON logs.

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)