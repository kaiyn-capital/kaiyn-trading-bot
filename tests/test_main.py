import logging
from unittest.mock import MagicMock, patch

from app.main import setup_logging
from tests.settings_factory import make_settings


def test_setup_logging_info_level():
    settings = make_settings(log_level="INFO", retention_days=30)

    with (
        patch("app.main.Path.mkdir") as mock_mkdir,
        patch("app.main.TimedRotatingFileHandler") as mock_trfh,
        patch("app.main.logging.basicConfig") as mock_basic_config,
        patch("app.main.logging.getLogger") as mock_get_logger,
        patch("app.main.logging.StreamHandler") as mock_stream_handler,
    ):
        mock_trfh_instance = MagicMock()
        mock_trfh.return_value = mock_trfh_instance

        mock_stream_handler_instance = MagicMock()
        mock_stream_handler.return_value = mock_stream_handler_instance

        mock_httpx_logger = MagicMock()
        mock_telegram_logger = MagicMock()
        mock_sqlalchemy_logger = MagicMock()

        def get_logger_side_effect(name):
            if name == "httpx":
                return mock_httpx_logger
            if name == "telegram":
                return mock_telegram_logger
            if name == "sqlalchemy.engine":
                return mock_sqlalchemy_logger
            return MagicMock()

        mock_get_logger.side_effect = get_logger_side_effect

        setup_logging(settings)

        # Check Path("logs").mkdir
        mock_mkdir.assert_called_once_with(exist_ok=True)

        # Check TimedRotatingFileHandler
        mock_trfh.assert_called_once_with(
            "logs/app.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )

        # Check basicConfig
        mock_basic_config.assert_called_once_with(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[mock_stream_handler_instance, mock_trfh_instance],
            force=True,
        )

        # Check getLogger().setLevel
        mock_httpx_logger.setLevel.assert_called_once_with(logging.WARNING)
        mock_telegram_logger.setLevel.assert_called_once_with(logging.WARNING)
        mock_sqlalchemy_logger.setLevel.assert_called_once_with(logging.WARNING)


def test_setup_logging_debug_level():
    settings = make_settings(log_level="DEBUG")

    with (
        patch("app.main.Path.mkdir"),
        patch("app.main.TimedRotatingFileHandler"),
        patch("app.main.logging.basicConfig") as mock_basic_config,
        patch("app.main.logging.getLogger"),
        patch("app.main.logging.StreamHandler"),
    ):
        setup_logging(settings)

        # basicConfig should use DEBUG level
        args, kwargs = mock_basic_config.call_args
        assert kwargs["level"] == logging.DEBUG


def test_setup_logging_invalid_level():
    settings = make_settings(log_level="INVALID_LEVEL")

    with (
        patch("app.main.Path.mkdir"),
        patch("app.main.TimedRotatingFileHandler"),
        patch("app.main.logging.basicConfig") as mock_basic_config,
        patch("app.main.logging.getLogger"),
        patch("app.main.logging.StreamHandler"),
    ):
        setup_logging(settings)

        # basicConfig should use INFO level as fallback
        args, kwargs = mock_basic_config.call_args
        assert kwargs["level"] == logging.INFO
