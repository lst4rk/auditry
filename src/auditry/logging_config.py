"""
Structured logging configuration using structlog.

This module provides JSON-formatted logging that integrates with
correlation IDs and is optimized for log aggregators like Datadog.
"""

import logging
import sys
import warnings
from collections.abc import Iterable
from typing import Optional

import structlog

try:
    import sentry_sdk
except ImportError:  # pragma: no cover - optional dependency
    sentry_sdk = None

_SENTRY_LEVELS = {"error": "error", "exception": "error", "critical": "fatal"}

# structlog event_dict keys forwarded to Sentry as tags. Deliberately narrow:
# _log_failure stores request/response bodies in the event dict, and shipping
# those to Sentry would route payload data around auditry's redaction contract.
_SENTRY_CONTEXT_KEYS = (
    "correlation_id",
    "user_id",
    "service",
    "status_code",
    "exception_type",
)

# Loggers whose records Sentry's LoggingIntegration should not turn into
# message-based events: auditry emits its own exc_info-preserving capture for
# these, so leaving them enabled double-reports every error log.
_DEFAULT_SENTRY_IGNORE_LOGGERS = ("auditry.core.logger",)

# Latches after a capture failure so a persistent fault warns once instead of
# flooding the logs. Reset each time configure_logging runs.
_sentry_capture_disabled = False


def _capture_to_sentry(logger, method_name, event_dict):
    """
    Report error-level logs to Sentry before exc_info is flattened to a string.

    JSONRenderer hands stdlib logging a rendered string, so Sentry's
    LoggingIntegration never sees exc_info and falls back to message-based
    events grouped by the JSON blob. Capturing here preserves the exception
    for stacktrace grouping. Sentry's dedupe integration tracks the most
    recently captured exception, so back-to-back captures of the same error
    (e.g. middleware log then error handler log) collapse into one event;
    interleaved errors under concurrency may still occasionally double-report.
    No-op when sentry_sdk is absent or not initialized.
    """
    global _sentry_capture_disabled
    level = _SENTRY_LEVELS.get(method_name)
    if sentry_sdk is None or level is None or _sentry_capture_disabled:
        return event_dict
    try:
        # new_scope on sentry-sdk >=2, push_scope on >=1 (deprecated in 2 but
        # still present); the stub in tests only provides push_scope.
        scope_factory = getattr(sentry_sdk, "new_scope", None) or sentry_sdk.push_scope
        with scope_factory() as scope:
            for key in _SENTRY_CONTEXT_KEYS:
                if key in event_dict:
                    scope.set_tag(key, event_dict[key])
            exc_info = event_dict.get("exc_info")
            if exc_info is True:
                # exc_info=True resolves the ambient exception; outside an active
                # except block there is none, so capture_exception would send an
                # empty, untriageable event. Fall back to the message instead.
                if sys.exc_info()[0] is None:
                    sentry_sdk.capture_message(str(event_dict.get("event", "")), level=level)
                else:
                    sentry_sdk.capture_exception(None)
            elif exc_info:
                sentry_sdk.capture_exception(exc_info)
            else:
                sentry_sdk.capture_message(str(event_dict.get("event", "")), level=level)
    except Exception:  # pragma: no cover - reporting must never break logging
        # Latch off and say so once; a broken transport or an incompatible
        # sentry-sdk must not silently no-op forever or flood the logs.
        _sentry_capture_disabled = True
        logging.getLogger(__name__).warning(
            "auditry sentry capture failed; disabling for this process", exc_info=True
        )
    return event_dict


def configure_logging(
    level: str = "INFO",
    sentry_capture: bool = False,
    sentry_ignore_loggers: Optional[Iterable[str]] = None,
) -> None:
    """
    Configure application-wide structured logging using structlog.

    Sets up JSON-formatted logging with timestamps, log levels, and
    correlation IDs. Should be called once at application startup.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        sentry_capture: Report error-level logs to Sentry with exc_info
            intact. auditry suppresses Sentry's own LoggingIntegration for the
            loggers it captures (see sentry_ignore_loggers) so errors are not
            reported twice; consumers who route additional loggers through this
            pipeline should either add them there or set event_level=None on
            their own LoggingIntegration.
        sentry_ignore_loggers: Logger names to hand to Sentry's ignore_logger so
            LoggingIntegration stops creating message-based events for them.
            Defaults to auditry's own logger; pass an explicit iterable to
            extend or override.
    """
    global _sentry_capture_disabled
    _sentry_capture_disabled = False
    # Configure structlog processors
    processors = [
        # Add log level to event dict
        structlog.stdlib.add_log_level,
        # Add timestamp in ISO format
        structlog.processors.TimeStamper(fmt="iso"),
        # Add correlation_id from context if available
        structlog.contextvars.merge_contextvars,
    ]
    if sentry_capture:
        if sentry_sdk is None:
            warnings.warn(
                "sentry_capture=True but sentry-sdk is not installed; "
                "install auditry[sentry]. Sentry capture is disabled.",
                RuntimeWarning,
                stacklevel=2,
            )
        else:
            # Stop LoggingIntegration from also reporting these loggers as
            # JSON-blob-grouped message events (double-reporting otherwise).
            from sentry_sdk.integrations.logging import ignore_logger

            ignore = (
                _DEFAULT_SENTRY_IGNORE_LOGGERS
                if sentry_ignore_loggers is None
                else sentry_ignore_loggers
            )
            for name in ignore:
                ignore_logger(name)
            # Report to Sentry while exc_info is still an exception
            processors.append(_capture_to_sentry)
    processors += [
        # Format exceptions
        structlog.processors.format_exc_info,
        # Render as JSON
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=processors,
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
