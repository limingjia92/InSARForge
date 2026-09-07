"""Lightweight package-scoped logging configuration."""

import logging
from typing import TextIO

DEFAULT_LOG_FORMAT = "%(levelname)s | %(name)s | %(message)s"

_LOGGER_NAME = "insarforge"
_CONSOLE_HANDLER_NAME = "insarforge.console"


def configure_console_logging(
    level: int | str = logging.INFO,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configure and return the InSARForge package logger."""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        if handler.get_name() == _CONSOLE_HANDLER_NAME:
            logger.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler(stream)
    handler.set_name(_CONSOLE_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT))
    logger.addHandler(handler)

    return logger
