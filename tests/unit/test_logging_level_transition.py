"""Regression coverage for filtering after console reconfiguration."""

import io
import logging

import pytest

from insarforge.core.logging import configure_console_logging


@pytest.fixture
def isolated_package_logger():
    package = logging.getLogger("insarforge")
    handlers = list(package.handlers)
    level, propagate, disabled = package.level, package.propagate, package.disabled
    filters = list(package.filters)
    try:
        for handler in handlers:
            package.removeHandler(handler)
        for log_filter in filters:
            package.removeFilter(log_filter)
        package.disabled = False
        yield package
    finally:
        for handler in list(package.handlers):
            package.removeHandler(handler)
            if handler not in handlers:
                handler.close()
        for handler in handlers:
            package.addHandler(handler)
        for log_filter in list(package.filters):
            package.removeFilter(log_filter)
        for log_filter in filters:
            package.addFilter(log_filter)
        package.setLevel(level)
        package.propagate = propagate
        package.disabled = disabled


def test_reconfiguration_updates_level_filter_and_stream(isolated_package_logger):
    package = isolated_package_logger
    root = logging.getLogger()
    root_state = (
        list(root.handlers),
        root.level,
        root.propagate,
        root.disabled,
        list(root.filters),
    )
    info_stream, warning_stream, debug_stream = (
        io.StringIO(),
        io.StringIO(),
        io.StringIO(),
    )

    for level, stream in (
        (logging.INFO, info_stream),
        (logging.WARNING, warning_stream),
        (logging.DEBUG, debug_stream),
    ):
        assert configure_console_logging(level=level, stream=stream) is package
        owned = [
            handler
            for handler in package.handlers
            if handler.get_name() == "insarforge.console"
        ]
        assert len(owned) == 1
        package.debug("debug message")
        package.info("info message")
        package.warning("warning message")

        assert info_stream.getvalue() == (
            "INFO | insarforge | info message\nWARNING | insarforge | warning message\n"
        )
        if level in (logging.WARNING, logging.DEBUG):
            assert warning_stream.getvalue() == (
                "WARNING | insarforge | warning message\n"
            )

    assert debug_stream.getvalue() == (
        "DEBUG | insarforge | debug message\n"
        "INFO | insarforge | info message\n"
        "WARNING | insarforge | warning message\n"
    )
    assert (
        list(root.handlers),
        root.level,
        root.propagate,
        root.disabled,
        list(root.filters),
    ) == root_state
