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


def test_productdraft_is_type_checking_only():
    code = "import sys; import insarforge.contracts.plugins; assert 'insarforge.products.models' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)
