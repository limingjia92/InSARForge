"""PRO-P41-05: explicit operation-to-family Product transfer, not a runtime."""

import ast
import builtins
import io
import logging
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import MISSING, FrozenInstanceError, dataclass, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import get_type_hints

import pytest
from test_product_models import draft, populated_product, unknown

from insarforge.contracts import plugins
from insarforge.contracts.context import ExecutionContext, ResourceAllocation
from insarforge.contracts.identity import PluginDescriptor, PluginKind, PluginRef
from insarforge.contracts.operations import (
    InputPortContract,
    OperationHandler,
    OutputPortContract,
    PluginInstance,
    PreparedExecution,
    ProbeContext,
    ResolvedInput,
    ResolvedInputs,
    TaskOutcome,
)
from insarforge.contracts.records import AcquisitionMetadata, CorrectionSpec
from insarforge.contracts.values import ArtifactRef, FrozenJSON, freeze_json
from insarforge.core.registry import PluginRegistry
from insarforge.products.models import Product, ProductDraft
from insarforge.products.semantics import SemanticValue
from insarforge.products.validation import ProductValidationReport


def artifact(product):
    return ArtifactRef(
        product.product_id,
        product.schema_id,
        product.schema_version,
        "semantic:provided",
        "manifest:provided",
        "/must-not-read/product.json",
    )


def correction_spec():
    return CorrectionSpec(
        "synthetic:method",
        "input",
        "output",
        "stage",
        "mode",
        unknown(),
        unknown(),
        unknown(),
        {},
    )


FAMILIES = ("processing", "analysis", "correction", "inspection")


def request_for(family, inputs, parameters=None):
    parameters = {} if parameters is None else parameters
    if family == "processing":
        return plugins.ProcessingRequest(
            "test", "profile", 1, inputs, (), {}, parameters
        )
    if family == "analysis":
        return plugins.AnalysisRequest(inputs, {}, "profile", 1, parameters)
    if family == "correction":
        return plugins.CorrectionRequest(inputs, {}, correction_spec(), parameters)
    return plugins.InspectionRequest(inputs, parameters)


def product_map(request):
    if isinstance(request, plugins.CorrectionRequest):
        return request.source_inputs
    return request.product_inputs


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("unpaired", ["ref", "product", "resolved"])
def test_product_slots_reject_unpaired_or_implicitly_adapted_values(family, unpaired):
    product = populated_product()
    ref = artifact(product)
    value = {"ref": ref, "product": product, "resolved": ResolvedInput(ref, product)}[
        unpaired
    ]
    with pytest.raises(TypeError):
        request_for(family, value if family == "inspection" else {"source": [value]})


def test_product_input_exact_required_fields_and_frozen_identity():
    pair_type = plugins.ProductInput
    assert [f.name for f in fields(pair_type)] == ["artifact", "value"]
    assert all(
        f.default is MISSING and f.default_factory is MISSING for f in fields(pair_type)
    )
    assert get_type_hints(pair_type) == {"artifact": ArtifactRef, "value": Product}
    product = populated_product()
    ref = artifact(product)
    pair = pair_type(ref, product)
    assert pair.artifact is ref and pair.value is product
    for name in ("artifact", "value"):
        with pytest.raises(FrozenInstanceError):
            setattr(pair, name, None)
    with pytest.raises(TypeError):
        pair_type(ref)


@pytest.mark.parametrize("bad", [None, object(), "product", draft()])
def test_product_input_rejects_other_record_types(bad):
    product = populated_product()
    with pytest.raises(TypeError):
        plugins.ProductInput(artifact(product), bad)


def test_product_input_rejects_lookalikes_subclasses_and_nonproduct_resolved_record():
    product = populated_product()
    ref = artifact(product)
    metadata = AcquisitionMetadata(
        "a",
        ref.schema_id,
        ref.schema_version,
        ref,
        PluginRef(PluginKind.MISSION, "test:mission", 1),
        {},
        (),
        {},
    )
    assert ResolvedInput(ref, metadata).value is metadata
    with pytest.raises(TypeError):
        plugins.ProductInput(ref, metadata)
    ref_subclass = type("RefSubclass", (ArtifactRef,), {})(**vars(ref))
    product_subclass = type("ProductSubclass", (Product,), {})(**vars(product))
    for invalid_ref, invalid_product in (
        (ref_subclass, product),
        (ref, product_subclass),
        (object(), product),
    ):
        with pytest.raises(TypeError):
            plugins.ProductInput(invalid_ref, invalid_product)


@pytest.mark.parametrize(
    "changes", [{"schema_id": "wrong:schema"}, {"schema_version": 3}]
)
def test_product_input_rejects_schema_mismatch(changes):
    product = populated_product()
    with pytest.raises(ValueError):
        plugins.ProductInput(replace(artifact(product), **changes), product)


@pytest.mark.parametrize("family", FAMILIES)
def test_request_rejects_product_input_subclass(family):
    product = populated_product()
    subclass = type("PairSubclass", (plugins.ProductInput,), {})
    value = subclass(artifact(product), product)
    with pytest.raises(TypeError):
        request_for(family, value if family == "inspection" else {"source": [value]})


@pytest.mark.parametrize("family", FAMILIES[:3])
@pytest.mark.parametrize("view", [False, True])
def test_request_owns_input_collections_preserving_order_and_duplicates(family, view):
    product = populated_product()
    first = plugins.ProductInput(artifact(product), product)
    second = plugins.ProductInput(replace(first.artifact, record_id="second"), product)
    values = [second, first, second]
    source = {"z": values, "a": []}
    parameters = {"nested": [1]}
    request = request_for(
        family, MappingProxyType(source) if view else source, parameters
    )
    values.clear()
    source.clear()
    parameters["nested"].append(2)
    result = product_map(request)
    assert tuple(result) == ("z", "a")
    assert result["z"] == (second, first, second) and result["a"] == ()
    assert result["z"][0] is result["z"][2] is second
    assert result["z"][1] is first
    assert request.parameters["nested"] == (1,)
    with pytest.raises(TypeError):
        result["new"] = ()
    with pytest.raises(TypeError):
        result["z"][0] = first
    with pytest.raises(FrozenInstanceError):
        request.parameters = {}


@pytest.mark.parametrize("family", FAMILIES[:3])
@pytest.mark.parametrize(
    "inputs", [None, [], {"source": "ref"}, {"source": b"ref"}, {"source": [object()]}]
)
def test_product_maps_reject_invalid_collections(family, inputs):
    with pytest.raises(TypeError):
        request_for(family, inputs)


@pytest.mark.parametrize("family", FAMILIES[:3])
def test_product_maps_reject_invalid_port_names(family):
    with pytest.raises(ValueError):
        request_for(family, {"bad port": []})

    class MutableKey(str):
        pass

    with pytest.raises(TypeError):
        request_for(family, {MutableKey("source"): []})


def test_exact_request_fields_resolvable_hints_and_reference_slots():
    expected = {
        plugins.ProcessingRequest: (
            "purpose",
            "profile_id",
            "profile_version",
            "product_inputs",
            "acquisition_metadata_refs",
            "auxiliary_inputs",
            "parameters",
        ),
        plugins.AnalysisRequest: (
            "product_inputs",
            "auxiliary_inputs",
            "profile_id",
            "profile_version",
            "parameters",
        ),
        plugins.CorrectionRequest: (
            "source_inputs",
            "external_inputs",
            "spec",
            "parameters",
        ),
        plugins.InspectionRequest: ("source", "parameters"),
        plugins.AcquireRequest: ("catalog_ref", "entry_id", "parameters"),
        plugins.QCRequest: (
            "target_refs",
            "metric_profile_id",
            "metric_profile_version",
            "thresholds",
            "comparison_refs",
            "parameters",
        ),
    }
    for cls, names in expected.items():
        assert tuple(f.name for f in fields(cls)) == names
        assert cls.__dataclass_params__.frozen
        assert all(
            f.default is MISSING and f.default_factory is MISSING for f in fields(cls)
        )
        assert tuple(get_type_hints(cls)) == names
    for cls, field in (
        (plugins.ProcessingRequest, "product_inputs"),
        (plugins.AnalysisRequest, "product_inputs"),
        (plugins.CorrectionRequest, "source_inputs"),
    ):
        assert (
            get_type_hints(cls)[field] == Mapping[str, tuple[plugins.ProductInput, ...]]
        )
    assert get_type_hints(plugins.InspectionRequest)["source"] is plugins.ProductInput
    product = populated_product()
    ref = artifact(product)
    refs = [ref, ref]
    reference_map = {"aux": refs}
    requests = [
        plugins.ProcessingRequest("test", "profile", 1, {}, refs, reference_map, {}),
        plugins.AnalysisRequest({}, reference_map, "profile", 1, {}),
        plugins.CorrectionRequest({}, reference_map, correction_spec(), {}),
        plugins.AcquireRequest(ref, "entry", {}),
        plugins.QCRequest(refs, "metrics", 1, {}, refs, {}),
    ]
    refs.clear()
    reference_map.clear()
    for request, field in zip(
        requests[:3],
        ("auxiliary_inputs", "auxiliary_inputs", "external_inputs"),
        strict=True,
    ):
        assert (
            get_type_hints(type(request))[field]
            == Mapping[str, tuple[ArtifactRef, ...]]
        )
        assert getattr(request, field)["aux"] == (ref, ref)
    assert requests[0].acquisition_metadata_refs == (ref, ref)
    assert requests[3].catalog_ref is ref
    assert requests[4].target_refs == requests[4].comparison_refs == (ref, ref)
    assert get_type_hints(plugins.AcquireRequest)["catalog_ref"] is ArtifactRef
    for cls, field in (
        (plugins.ProcessingRequest, "acquisition_metadata_refs"),
        (plugins.QCRequest, "target_refs"),
        (plugins.QCRequest, "comparison_refs"),
    ):
        assert get_type_hints(cls)[field] == tuple[ArtifactRef, ...]
    pair = plugins.ProductInput(ref, product)
    for request, field, invalid in (
        (requests[0], "acquisition_metadata_refs", [pair]),
        (requests[0], "auxiliary_inputs", {"aux": [pair]}),
        (requests[1], "auxiliary_inputs", {"aux": [pair]}),
        (requests[2], "external_inputs", {"aux": [pair]}),
        (requests[3], "catalog_ref", pair),
        (requests[4], "target_refs", [pair]),
        (requests[4], "comparison_refs", [pair]),
    ):
        with pytest.raises(TypeError):
            replace(request, **{field: invalid})


class FakeProcessor:
    descriptor = PluginDescriptor(
        PluginKind.PROCESSOR, "test:processor", 1, "1", "Test", ()
    )

    def process(
        self, request: plugins.ProcessingRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]:
        self.seen = request.product_inputs["source"][0]
        self.context = context
        return ()


class FakeAnalyzer:
    descriptor = PluginDescriptor(
        PluginKind.ANALYZER, "test:analyzer", 1, "1", "Test", ()
    )

    def analyze(
        self, request: plugins.AnalysisRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]:
        self.seen = request.product_inputs["source"][0]
        self.context = context
        return ()


class FakeCorrection:
    descriptor = PluginDescriptor(
        PluginKind.CORRECTION, "test:correction", 1, "1", "Test", ()
    )

    def correct(
        self, request: plugins.CorrectionRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]:
        self.seen = request.source_inputs["source"][0]
        self.context = context
        return ()


class FakeMission:
    descriptor = PluginDescriptor(
        PluginKind.MISSION, "test:mission", 1, "1", "Test", ()
    )

    def inspect(
        self, request: plugins.InspectionRequest, context: ExecutionContext
    ) -> AcquisitionMetadata:
        self.seen = request.source
        self.context = context
        return AcquisitionMetadata(
            "metadata",
            "synthetic:metadata",
            1,
            request.source.artifact,
            PluginRef(PluginKind.MISSION, "test:mission", 1),
            {},
            (),
            {},
        )


class ExplicitProductHandler:
    """Test-only request adaptation; no loading, scheduling or output publication."""

    def validate_spec(
        self,
        parameters: FrozenJSON,
        inputs: tuple[InputPortContract, ...],
        outputs: tuple[OutputPortContract, ...],
    ) -> ProductValidationReport:
        pytest.fail("static validation is outside this transfer test")

    def prepare(
        self,
        plugin: PluginInstance,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        probe_context: ProbeContext,
    ) -> PreparedExecution:
        pytest.fail("preparation is outside this transfer test")

    def invoke(
        self,
        plugin: PluginInstance,
        prepared: PreparedExecution,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        context: ExecutionContext,
    ) -> TaskOutcome:
        resolved = resolved_inputs["source"][0]
        pair = plugins.ProductInput(resolved.artifact, resolved.value)
        inputs = {"source": [pair]}
        if isinstance(plugin, FakeProcessor):
            plugin.process(request_for("processing", inputs, parameters), context)
        elif isinstance(plugin, FakeAnalyzer):
            plugin.analyze(request_for("analysis", inputs, parameters), context)
        elif isinstance(plugin, FakeCorrection):
            plugin.correct(request_for("correction", inputs, parameters), context)
        else:
            plugin.inspect(request_for("inspection", pair, parameters), context)
        return TaskOutcome({}, ())


@dataclass(frozen=True)
class FakePrepared:
    semantic_execution_identity: SemanticValue[FrozenJSON]
    preparation: FrozenJSON


def test_transfer_fakes_conform_to_existing_adapter_and_family_signatures():
    for method in ("validate_spec", "prepare", "invoke"):
        assert get_type_hints(
            getattr(ExplicitProductHandler, method)
        ) == get_type_hints(getattr(OperationHandler, method))
    for fake, protocol, method in (
        (FakeProcessor, plugins.Processor, "process"),
        (FakeAnalyzer, plugins.Analyzer, "analyze"),
        (FakeCorrection, plugins.Correction, "correct"),
        (FakeMission, plugins.Mission, "inspect"),
    ):
        assert get_type_hints(getattr(fake, method)) == get_type_hints(
            getattr(protocol, method)
        )


@pytest.mark.parametrize(
    "plugin_type", [FakeProcessor, FakeAnalyzer, FakeCorrection, FakeMission]
)
def test_handler_explicitly_transfers_same_product_and_ref_without_io_or_services(
    plugin_type, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail(
            "Product transfer attempted I/O, registry lookup or a context callback"
        )

    product = populated_product()
    ref = artifact(product)
    resolved = ResolvedInput(ref, product)
    context = ExecutionContext(
        "run",
        "task",
        "attempt",
        Path("attempt"),
        Path("artifact"),
        Path("scratch"),
        ResourceAllocation(1, None, 0),
        logging.getLogger(__name__),
        forbidden,
    )
    assert not hasattr(context, "services")
    plugin = plugin_type()
    handler: OperationHandler = ExplicitProductHandler()
    prepared: PreparedExecution = FakePrepared(unknown(), freeze_json({}))
    with monkeypatch.context() as guard:
        for owner, name in (
            (builtins, "open"),
            (io, "open"),
            (os, "open"),
            (Path, "read_bytes"),
            (Path, "read_text"),
            (PluginRegistry, "resolve"),
            (PluginRegistry, "resolve_binding"),
        ):
            guard.setattr(owner, name, forbidden)
        outcome = handler.invoke(
            plugin, prepared, {"source": (resolved,)}, freeze_json({}), context
        )
        assert plugin.seen.value is product
        assert plugin.seen.artifact is ref
        assert plugin.context is context
        assert outcome.outputs == {} and outcome.evidence == ()


def test_plugins_import_direction_and_fresh_process_type_hints():
    tree = ast.parse(Path(plugins.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "insarforge.contracts.operations"
            assert not (
                node.module == "insarforge.contracts"
                and any(a.name == "operations" for a in node.names)
            )
        elif isinstance(node, ast.Import):
            assert all(a.name != "insarforge.contracts.operations" for a in node.names)
    code = """
import sys
from typing import get_type_hints
from insarforge.contracts import plugins
assert 'insarforge.contracts.operations' not in sys.modules
assert not {'numpy', 'pydantic', 'yaml', 'h5py', 'osgeo', 'earthaccess'} & set(sys.modules)
for cls in (plugins.ProductInput, plugins.InspectionRequest, plugins.ProcessingRequest, plugins.AnalysisRequest, plugins.CorrectionRequest):
    get_type_hints(cls)
for cls, method in ((plugins.Mission, 'inspect'), (plugins.Provider, 'search'), (plugins.Provider, 'acquire'), (plugins.Processor, 'process'), (plugins.Correction, 'correct'), (plugins.Analyzer, 'analyze'), (plugins.QC, 'assess')):
    get_type_hints(getattr(cls, method))
from insarforge.contracts import operations
get_type_hints(operations.OperationHandler.invoke)
"""
    subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True
    )
