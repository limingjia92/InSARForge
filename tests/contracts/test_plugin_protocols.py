import inspect
import subprocess
import sys
from typing import Protocol

from insarforge.contracts.plugins import (
    QC,
    Analyzer,
    Correction,
    Mission,
    Processor,
    Provider,
)


def test_protocol_shapes():
    expected = {
        Mission: ["descriptor", "inspect"],
        Provider: ["descriptor", "search", "acquire"],
        Processor: ["descriptor", "process"],
        Correction: ["descriptor", "correct"],
        Analyzer: ["descriptor", "analyze"],
        QC: ["descriptor", "assess"],
    }
    for cls, names in expected.items():
        assert issubclass(cls, Protocol)
        assert "run" not in cls.__dict__
        assert [n for n in cls.__dict__ if not n.startswith("_")] == names


def test_protocol_signatures():
    assert list(inspect.signature(Mission.inspect).parameters) == [
        "self",
        "request",
        "context",
    ]
    assert list(inspect.signature(Provider.search).parameters) == [
        "self",
        "request",
        "context",
    ]
    assert list(inspect.signature(Provider.acquire).parameters) == [
        "self",
        "request",
        "context",
    ]
    assert list(inspect.signature(Processor.process).parameters) == [
        "self",
        "request",
        "context",
    ]
    assert list(inspect.signature(Correction.correct).parameters) == [
        "self",
        "request",
        "context",
    ]
    assert list(inspect.signature(Analyzer.analyze).parameters) == [
        "self",
        "request",
        "context",
    ]
    assert list(inspect.signature(QC.assess).parameters) == [
        "self",
        "request",
        "context",
    ]
    assert Processor not in Correction.__mro__
    assert Processor not in Analyzer.__mro__


def test_product_types_resolve_without_loading_operations():
    code = """
import sys
from typing import get_type_hints
from insarforge.contracts import plugins
from insarforge.products.models import Product, ProductDraft
assert get_type_hints(plugins.ProductInput)['value'] is Product
assert get_type_hints(plugins.Provider.acquire)['return'] is ProductDraft
assert 'insarforge.contracts.operations' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True)
