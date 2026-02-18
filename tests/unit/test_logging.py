"""Unit tests for logging module."""

from unittest.mock import patch

from app.core.logging import setup_logging


def test_setup_logging():
    with patch("app.core.logging.get_settings") as mock_settings:
        mock_settings.return_value.app.log_level.value = "INFO"
        mock_settings.return_value.observability.log_record_format = "json"
        setup_logging()


def test_setup_logging_console():
    with patch("app.core.logging.get_settings") as mock_settings:
        mock_settings.return_value.app.log_level.value = "DEBUG"
        mock_settings.return_value.observability.log_record_format = "console"
        setup_logging()
