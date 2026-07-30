"""
Structured logging configuration using structlog.

This module provides JSON-formatted logging that integrates with
correlation IDs and is optimized for log aggregators like Datadog.
"""

import logging
import sys
import warnings
from collections.abc import Iterable, MutableMapping
from typing import Any, Literal, Optional

import structlog

try:
    import sentry_sdk
except ImportError:  # pragma: no cover - optional dependency
    sentry_sdk = None  # type: ignore[assignment]

# Values are a subset of sentry-sdk's LogLevelStr; typed so capture_message's
# level argument satisfies strict mypy without importing sentry's private types.
_SentryLevel = Literal["error", "fatal"]
_SENTRY_LEVELS: dict[str, _SentryLevel] = {
    "error": "error",
    "exception": "error",
    "critical": "fatal",
}

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

# Set after the first capture failure so a persistent fault is reported once
# instead of flooding the logs; capture keeps being attempted regardless.
# Reset each time configure_logging runs.
_sentry_capture_warned = False


def _capture_to_sentry(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
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
    level = _SENTRY_LEVELS.get(method_name)
    if sentry_sdk is None or level is None:
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
        # Never raise out of logging, but don't go silent-forever either: report
        # once at ERROR (so it can reach Sentry for consumers who keep
        # event_level on) and keep trying. A transient transport fault or a
        # single bad value must not disable all capture for the process.
        global _sentry_capture_warned
        if not _sentry_capture_warned:
            _sentry_capture_warned = True
            logging.getLogger(__name__).error(
                "auditry sentry capture failed; capture continues but events may be lost",
                exc_info=True,
            )
    return event_dict


def _logging_integration_double_reports() -> bool:
    """
    True when Sentry's LoggingIntegration will also create events for error logs.

    Its handler defaults to event_level=ERROR, so with sentry_capture the same
    error is reported twice (our exc_info capture plus a JSON-blob message).
    ignore_logger only covers exact logger names, so consumer loggers still
    double-report; detect the conflict here rather than leaving it to prose.
    Probing must never break configure_logging, so any failure reads as "no".
    """
    try:
        get_client = getattr(sentry_sdk, "get_client", None)
        if get_client is None:  # sentry-sdk <2 or stubbed in tests
            return False
        integrations = getattr(get_client(), "integrations", None) or {}
        handler = getattr(integrations.get("logging"), "_handler", None)
        return handler is not None and handler.level <= logging.ERROR
    except Exception:  # pragma: no cover - detection is best-effort
        return False


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
        sentry_ignore_loggers: Additional logger names handed to Sentry's
            ignore_logger so LoggingIntegration stops creating message-based
            events for them. Unioned with auditry's own logger, never replacing
            it. Names are matched exactly by record name, not hierarchically, so
            "pkg" does not cover "pkg.module".
    """
    global _sentry_capture_warned
    _sentry_capture_warned = False
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
            # Union with the default so a caller covering their own loggers can
            # never silently re-enable double-reporting of auditry's own.
            from sentry_sdk.integrations.logging import ignore_logger

            ignore = set(_DEFAULT_SENTRY_IGNORE_LOGGERS)
            if sentry_ignore_loggers is not None:
                ignore |= set(sentry_ignore_loggers)
            for name in ignore:
                ignore_logger(name)
            # ignore_logger only covers exact names, so consumer loggers still
            # double-report under a stock init. Warn instead of leaving it to
            # the README.
            if _logging_integration_double_reports():
                warnings.warn(
                    "auditry sentry_capture is enabled while Sentry's "
                    "LoggingIntegration still creates events (event_level<=ERROR); "
                    "error logs from loggers other than auditry's own will be "
                    "reported twice. Pass LoggingIntegration(event_level=None) to "
                    "sentry_sdk.init().",
                    RuntimeWarning,
                    stacklevel=2,
                )
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
