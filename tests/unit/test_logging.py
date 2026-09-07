import io
import logging

import pytest

from insarforge.core.logging import DEFAULT_LOG_FORMAT, configure_console_logging


@pytest.fixture
def clean_logging_state():
    root = logging.getLogger()
    package = logging.getLogger("insarforge")
    root_level, root_handlers = root.level, list(root.handlers)
    package_level, package_handlers = package.level, list(package.handlers)
    package_propagate = package.propagate
    try:
        yield root, package
    finally:
        for handler in list(root.handlers):
            if handler not in root_handlers:
                root.removeHandler(handler)
                handler.close()
        for handler in root_handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.setLevel(root_level)
        for handler in list(package.handlers):
            if handler not in package_handlers:
                package.removeHandler(handler)
                handler.close()
        for handler in package_handlers:
            if handler not in package.handlers:
                package.addHandler(handler)
        package.setLevel(package_level)
        package.propagate = package_propagate


def test_default_format():
    assert DEFAULT_LOG_FORMAT == "%(levelname)s | %(name)s | %(message)s"


def test_configures_package_logger_and_child_output(clean_logging_state):
    _root, package = clean_logging_state
    buffer = io.StringIO()
    assert configure_console_logging(stream=buffer) is package
    logging.getLogger("insarforge.smoke").info("hello")
    assert buffer.getvalue() == "INFO | insarforge.smoke | hello\n"
    assert package.propagate is False


def test_reconfiguration_keeps_one_owned_handler_and_updates_stream(
    clean_logging_state,
):
    _root, package = clean_logging_state
    first, second = io.StringIO(), io.StringIO()
    configure_console_logging(stream=first)
    configure_console_logging(stream=second)
    logging.getLogger("insarforge.smoke").info("hello")
    owned = [
        handler
        for handler in package.handlers
        if handler.get_name() == "insarforge.console"
    ]
    assert len(owned) == 1
    assert first.getvalue() == ""
    assert second.getvalue() == "INFO | insarforge.smoke | hello\n"


def test_unrelated_handler_and_root_state_are_preserved(clean_logging_state):
    root, package = clean_logging_state
    root_level, root_handlers = root.level, list(root.handlers)
    unrelated = logging.NullHandler()
    package.addHandler(unrelated)
    configure_console_logging(stream=io.StringIO())
    assert unrelated in package.handlers
    assert root.level == root_level
    assert root.handlers == root_handlers


def test_debug_level_is_supported(clean_logging_state):
    buffer = io.StringIO()
    configure_console_logging(level="DEBUG", stream=buffer)
    logging.getLogger("insarforge.smoke").debug("debug")
    assert buffer.getvalue() == "DEBUG | insarforge.smoke | debug\n"
