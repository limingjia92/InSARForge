import dataclasses
import logging
from pathlib import Path

import pytest

from insarforge.contracts.context import (
    ExecutionContext,
    ResourceAllocation,
    ResourceRequest,
)


def test_resources():
    assert ResourceRequest() == ResourceRequest(1, None, 0)
    assert ResourceRequest(2, 3, 1) != ResourceAllocation(2, 3, 1)
    assert not issubclass(ResourceAllocation, ResourceRequest)
    for cls in (ResourceRequest, ResourceAllocation):
        with pytest.raises((TypeError, ValueError)):
            cls(0, None, 0)
        with pytest.raises(TypeError):
            cls(True, None, 0)


def test_context():
    called = []
    ctx = ExecutionContext(
        "r",
        "t",
        "a",
        Path("x"),
        Path("y"),
        Path("z"),
        ResourceAllocation(1, None, 0),
        logging.getLogger("x"),
        lambda: called.append(1),
    )
    assert [f.name for f in dataclasses.fields(ctx)] == [
        "run_id",
        "task_id",
        "attempt_id",
        "attempt_dir",
        "artifact_dir",
        "scratch_dir",
        "allocated_resources",
        "logger",
        "cancellation_requested",
    ]
    assert not called
    with pytest.raises(TypeError):
        ExecutionContext(
            "r",
            "t",
            "a",
            "x",
            Path("y"),
            Path("z"),
            ctx.allocated_resources,
            ctx.logger,
            lambda: False,
        )
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.run_id = "x"
