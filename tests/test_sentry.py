"""Tests for the Sentry integration helper."""

from unittest.mock import patch

from auditry.sentry import configure_sentry


def test_configure_sentry_skips_when_dsn_is_none():
    with patch("sentry_sdk.init") as mock_init:
        configure_sentry(dsn=None, environment="local")

    mock_init.assert_not_called()


def test_configure_sentry_skips_when_dsn_is_empty_string():
    with patch("sentry_sdk.init") as mock_init:
        configure_sentry(dsn="", environment="local")

    mock_init.assert_not_called()


def test_configure_sentry_calls_init_with_correct_params():
    with patch("sentry_sdk.init") as mock_init:
        configure_sentry(
            dsn="https://examplePublicKey@o0.ingest.sentry.io/0",
            environment="prod",
            traces_sample_rate=0.5,
            send_default_pii=False,
        )

    mock_init.assert_called_once()
    call_kwargs = mock_init.call_args[1]
    assert call_kwargs["dsn"] == "https://examplePublicKey@o0.ingest.sentry.io/0"
    assert call_kwargs["environment"] == "prod"
    assert call_kwargs["traces_sample_rate"] == 0.5
    assert call_kwargs["send_default_pii"] is False
    assert call_kwargs["enable_tracing"] is True


def test_configure_sentry_passes_extra_kwargs():
    with patch("sentry_sdk.init") as mock_init:
        configure_sentry(
            dsn="https://key@sentry.io/0",
            environment="dev",
            release="1.0.0",
            server_name="web-01",
        )

    call_kwargs = mock_init.call_args[1]
    assert call_kwargs["release"] == "1.0.0"
    assert call_kwargs["server_name"] == "web-01"


def test_configure_sentry_before_send_attaches_request_id():
    with patch("sentry_sdk.init") as mock_init:
        configure_sentry(
            dsn="https://key@sentry.io/0",
            environment="dev",
        )

    call_kwargs = mock_init.call_args[1]
    before_send = call_kwargs["before_send"]

    with patch("auditry.correlation.correlation_id") as mock_cid:
        mock_cid.get.return_value = "req-abc-123"
        event = {"tags": {}}
        result = before_send(event, {})

    assert result["tags"]["request_id"] == "req-abc-123"


def test_configure_sentry_before_send_creates_tags_if_missing():
    with patch("sentry_sdk.init") as mock_init:
        configure_sentry(
            dsn="https://key@sentry.io/0",
            environment="dev",
        )

    call_kwargs = mock_init.call_args[1]
    before_send = call_kwargs["before_send"]

    with patch("auditry.correlation.correlation_id") as mock_cid:
        mock_cid.get.return_value = "req-xyz"
        event = {}
        result = before_send(event, {})

    assert result["tags"]["request_id"] == "req-xyz"


def test_configure_sentry_before_send_skips_when_no_request_id():
    with patch("sentry_sdk.init") as mock_init:
        configure_sentry(
            dsn="https://key@sentry.io/0",
            environment="dev",
        )

    call_kwargs = mock_init.call_args[1]
    before_send = call_kwargs["before_send"]

    with patch("auditry.correlation.correlation_id") as mock_cid:
        mock_cid.get.return_value = None
        event = {}
        result = before_send(event, {})

    assert "tags" not in result
