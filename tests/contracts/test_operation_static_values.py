import ast
import builtins
import io
import socket
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

import pytest

from insarforge.contracts import operations, plugins
from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.operations import (
    ArtifactDraft,
    InputRecord,
    OutputRecord,
    PluginInstance,
    PortRecord,
    ProductProfileRef,
    RecordSchemaRef,
    ResolvedInput,
    ResolvedInputs,
    TaskOutcome,
)
from insarforge.contracts.records import (
    AcquisitionMetadata,
    CatalogSnapshot,
    QCReport,
    QCStatus,
)
from insarforge.contracts.values import ArtifactRef
from insarforge.products.assets import (
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.models import (
    ProducerRef,
    Product,
    ProductDraft,
    ProductionRef,
)
from insarforge.products.profiles import ProductProfile
from insarforge.products.semantics import SemanticStatus, SemanticValue


class StringSubclass(str):
    pass


class IntegerSubclass(int):
    pass


def artifact(schema_id="synthetic:record", schema_version=1):
    return ArtifactRef(
        "synthetic:reference",
        schema_id,
        schema_version,
        None,
        "digest",
        "/absent/record",
    )


def product_draft():
    return ProductDraft(
        "synthetic:kind", "synthetic:profile", 1, (), (), (), (), {}, {}
    )


def product():
    content = product_draft()
    unknown = SemanticValue(SemanticStatus.UNKNOWN, None, "synthetic:unverified", ())
    return Product(
        **{field.name: getattr(content, field.name) for field in fields(content)},
        schema_id="insarforge:product",
        schema_version=2,
        product_id="synthetic:product",
        producer=ProducerRef(
            PluginRef(PluginKind.PROCESSOR, "synthetic:processor", 1),
            "synthetic-version",
            unknown,
            unknown,
        ),
        produced_by=ProductionRef(unknown, "synthetic:output", "synthetic:attempt"),
        lineage=(),
        provenance_ref="synthetic:provenance",
    )


def record(record_type=QCReport, extensions=None):
    extensions = {} if extensions is None else extensions
    if record_type is CatalogSnapshot:
        return CatalogSnapshot(
            "synthetic:record-id",
            "synthetic:record",
            1,
            PluginRef(PluginKind.PROVIDER, "synthetic:provider", 1),
            "synthetic:query",
            1,
            {},
            (),
            extensions,
        )
    if record_type is AcquisitionMetadata:
        return AcquisitionMetadata(
            "synthetic:record-id",
            "synthetic:record",
            1,
            artifact(),
            PluginRef(PluginKind.MISSION, "synthetic:mission", 1),
            {},
            (),
            extensions,
        )
    return QCReport(
        "synthetic:record-id",
        "synthetic:record",
        1,
        QCStatus.NOT_EVALUATED,
        "synthetic:method",
        "1",
        (),
        (),
        (),
        extensions,
    )


def evidence(asset_id="synthetic:evidence"):
    return NativeAsset(
        asset_id,
        AssetKind.FILE,
        AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, "/absent/evidence", None),
        None,
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "value_type,expected",
    [
        (RecordSchemaRef, {"schema_id": str, "schema_version": int}),
        (ProductProfileRef, {"profile_id": str, "profile_version": int}),
        (ResolvedInput, {"artifact": ArtifactRef, "value": InputRecord}),
        (ArtifactDraft, {"schema": RecordSchemaRef, "value": OutputRecord}),
        (
            TaskOutcome,
            {
                "outputs": Mapping[str, tuple[ArtifactDraft, ...]],
                "evidence": tuple[NativeAsset, ...],
            },
        ),
    ],
)
def test_exact_required_fields_and_resolvable_types(value_type, expected):
    declared = fields(value_type)
    assert tuple(field.name for field in declared) == tuple(expected)
    assert get_type_hints(value_type) == expected
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in declared
    )
    assert value_type.__dataclass_params__.frozen


@pytest.mark.parametrize("version", [1, 2, 101])
def test_record_schema_ref_valid(version):
    schema = RecordSchemaRef("Synthetic:schema-v1", version)
    assert (schema.schema_id, schema.schema_version) == ("Synthetic:schema-v1", version)


@pytest.mark.parametrize("schema_id", [None, 1, b"schema", StringSubclass("schema")])
def test_record_schema_ref_requires_exact_string(schema_id):
    with pytest.raises(TypeError):
        RecordSchemaRef(schema_id, 1)


@pytest.mark.parametrize(
    "schema_id", ["", " leading", "trailing ", "a b", "a\t", "a\x00", "a\u200b"]
)
def test_record_schema_ref_invalid_identifier(schema_id):
    with pytest.raises(ValueError):
        RecordSchemaRef(schema_id, 1)


@pytest.mark.parametrize("version", [True, False, 1.0, "1", None, IntegerSubclass(1)])
def test_record_schema_ref_requires_exact_integer(version):
    with pytest.raises(TypeError):
        RecordSchemaRef("synthetic:schema", version)


@pytest.mark.parametrize("version", [0, -1])
def test_record_schema_ref_requires_positive_version(version):
    with pytest.raises(ValueError):
        RecordSchemaRef("synthetic:schema", version)


@pytest.mark.parametrize(
    "profile_id,version,error",
    [
        ("synthetic:profile", 1, None),
        (StringSubclass("synthetic:profile"), IntegerSubclass(2), None),
        ("", 1, ValueError),
        ("bad id", 1, ValueError),
        ("bad\u200b", 1, ValueError),
        (None, 1, TypeError),
        (1, 1, TypeError),
        ("synthetic:profile", "1", ValueError),
        ("synthetic:profile", 1.0, ValueError),
        ("synthetic:profile", None, ValueError),
        ("synthetic:profile", 0, ValueError),
        ("synthetic:profile", -1, ValueError),
        ("synthetic:profile", True, ValueError),
        ("synthetic:profile", False, ValueError),
    ],
)
def test_profile_identity_matches_existing_product_profile(profile_id, version, error):
    constructors = (
        lambda: ProductProfileRef(profile_id, version),
        lambda: ProductProfile(profile_id, version, (), (), (), (), {}),
    )
    for construct in constructors:
        if error is not None:
            with pytest.raises(error):
                construct()
        else:
            value = construct()
            assert (value.profile_id, value.profile_version) == (profile_id, version)


def test_exact_six_family_alias_and_bounded_record_aliases():
    assert set(get_args(PluginInstance)) == {
        plugins.Mission,
        plugins.Provider,
        plugins.Processor,
        plugins.Correction,
        plugins.Analyzer,
        plugins.QC,
    }
    other_records = {CatalogSnapshot, AcquisitionMetadata, QCReport}
    assert set(get_args(InputRecord)) == {Product} | other_records
    assert set(get_args(OutputRecord)) == {ProductDraft} | other_records
    assert set(get_args(PortRecord)) == {Product, ProductDraft} | other_records
    assert get_origin(ResolvedInputs) is Mapping
    key, members = get_args(ResolvedInputs)
    assert key is str
    assert get_origin(members) is tuple
    assert get_args(members) == (ResolvedInput, Ellipsis)
    assert not hasattr(operations, "Plugin")


@pytest.fixture(params=[CatalogSnapshot, AcquisitionMetadata, QCReport, Product])
def input_record(request):
    return product() if request.param is Product else record(request.param)


@pytest.fixture(params=[CatalogSnapshot, AcquisitionMetadata, QCReport, ProductDraft])
def output_record(request):
    return product_draft() if request.param is ProductDraft else record(request.param)


def test_resolved_input_retains_supplied_reference_and_record(input_record):
    ref = artifact(input_record.schema_id, input_record.schema_version)
    resolved = ResolvedInput(ref, input_record)
    assert resolved.artifact is ref
    assert resolved.value is input_record
    # Schema agreement does not claim record-ID or byte-integrity verification.
    assert ref.record_id == "synthetic:reference"
    assert ref.semantic_digest is None


@pytest.mark.parametrize(
    "field,value", [("schema_id", "different:schema"), ("schema_version", 99)]
)
def test_resolved_input_rejects_schema_disagreement(input_record, field, value):
    ref = artifact(input_record.schema_id, input_record.schema_version)
    with pytest.raises(ValueError, match="schema"):
        ResolvedInput(replace(ref, **{field: value}), input_record)


@pytest.mark.parametrize("bad", [None, {}, "path", b"payload", object()])
def test_resolved_input_rejects_wrong_local_types(bad):
    with pytest.raises(TypeError):
        ResolvedInput(bad, record())
    with pytest.raises(TypeError):
        ResolvedInput(artifact(), bad)


def test_resolved_input_rejects_construction_side_product():
    with pytest.raises(TypeError):
        ResolvedInput(artifact("insarforge:product", 2), product_draft())


def test_artifact_draft_retains_schema_and_output_record(output_record):
    schema = (
        RecordSchemaRef("insarforge:product", 2)
        if type(output_record) is ProductDraft
        else RecordSchemaRef(output_record.schema_id, output_record.schema_version)
    )
    draft = ArtifactDraft(schema, output_record)
    assert draft.schema is schema
    assert draft.value is output_record


@pytest.mark.parametrize(
    "field,value", [("schema_id", "different:schema"), ("schema_version", 99)]
)
def test_artifact_draft_rejects_target_schema_disagreement(output_record, field, value):
    schema = (
        RecordSchemaRef("insarforge:product", 2)
        if type(output_record) is ProductDraft
        else RecordSchemaRef(output_record.schema_id, output_record.schema_version)
    )
    with pytest.raises(ValueError, match="schema"):
        ArtifactDraft(replace(schema, **{field: value}), output_record)


@pytest.mark.parametrize("bad", [None, {}, "path", b"payload", object()])
def test_artifact_draft_rejects_wrong_local_types(bad):
    with pytest.raises(TypeError):
        ArtifactDraft(bad, record())
    with pytest.raises(TypeError):
        ArtifactDraft(RecordSchemaRef("synthetic:record", 1), bad)


def test_artifact_draft_is_not_product_draft_or_finalized_product():
    schema = RecordSchemaRef("insarforge:product", 2)
    content = product_draft()
    wrapped = ArtifactDraft(schema, content)
    assert type(wrapped) is ArtifactDraft
    assert wrapped.value is content
    with pytest.raises(TypeError):
        ArtifactDraft(schema, product())
    with pytest.raises(ValueError):
        ArtifactDraft(RecordSchemaRef("insarforge:product-draft", 1), content)


def test_closed_record_domain_rejects_subclass_payloads():
    class ExtendedRecord(QCReport):
        pass

    original = record()
    extended = ExtendedRecord(
        **{field.name: getattr(original, field.name) for field in fields(original)}
    )
    with pytest.raises(TypeError):
        ResolvedInput(artifact(), extended)
    with pytest.raises(TypeError):
        ArtifactDraft(RecordSchemaRef("synthetic:record", 1), extended)


def test_task_outcome_snapshots_mapping_sequences_and_evidence():
    schema = RecordSchemaRef("synthetic:record", 1)
    first = ArtifactDraft(schema, record())
    second = ArtifactDraft(schema, replace(record(), record_id="synthetic:second"))
    members = [second, first, second]
    source = {"synthetic:z": members, "synthetic:a": []}
    asset = evidence()
    source_evidence = [asset]
    outcome = TaskOutcome(source, source_evidence)
    members.clear()
    source.clear()
    source_evidence.clear()
    assert tuple(outcome.outputs) == ("synthetic:z", "synthetic:a")
    assert outcome.outputs["synthetic:z"] == (second, first, second)
    assert outcome.outputs["synthetic:z"][0] is second
    assert outcome.outputs["synthetic:a"] == ()
    assert outcome.evidence == (asset,)
    with pytest.raises(TypeError):
        outcome.outputs["synthetic:new"] = ()
    with pytest.raises(TypeError):
        outcome.outputs["synthetic:z"][0] = first
    assert TaskOutcome({}, []).outputs == {}


@pytest.mark.parametrize("outputs", [None, [], [("port", ())], "port"])
def test_task_outcome_requires_mapping(outputs):
    with pytest.raises(TypeError):
        TaskOutcome(outputs, ())


@pytest.mark.parametrize(
    "port_id,error",
    [(1, TypeError), (None, TypeError), ("", ValueError), ("bad port", ValueError)],
)
def test_task_outcome_validates_port_identifiers(port_id, error):
    with pytest.raises(error):
        TaskOutcome({port_id: ()}, ())


@pytest.mark.parametrize(
    "members", [None, 1, [None], [record()], [product_draft()], [object()]]
)
def test_task_outcome_requires_draft_members(members):
    with pytest.raises(TypeError):
        TaskOutcome({"synthetic:port": members}, ())


@pytest.mark.parametrize("members", [None, 1, [None], [artifact()], [object()]])
def test_task_outcome_requires_native_asset_evidence(members):
    with pytest.raises(TypeError):
        TaskOutcome({}, members)


def test_task_outcome_rejects_duplicate_evidence_ids():
    first = evidence()
    same_id = replace(first, media_type="text/plain")
    with pytest.raises(ValueError, match="duplicate evidence"):
        TaskOutcome({}, [first, same_id])
    second = evidence("synthetic:second")
    assert TaskOutcome({}, [second, first]).evidence == (second, first)


@pytest.mark.parametrize(
    "record_type", [CatalogSnapshot, AcquisitionMetadata, QCReport, ProductDraft]
)
def test_wrappers_reuse_deep_owned_record_values(record_type):
    nested = {"synthetic:extension": {"values": [1]}}
    content = (
        replace(product_draft(), extensions=nested)
        if record_type is ProductDraft
        else record(record_type, nested)
    )
    schema = (
        RecordSchemaRef("insarforge:product", 2)
        if record_type is ProductDraft
        else RecordSchemaRef("synthetic:record", 1)
    )
    draft = ArtifactDraft(schema, content)
    outcome = TaskOutcome({"synthetic:port": [draft]}, [])
    nested["synthetic:extension"]["values"].append(2)
    assert outcome.outputs["synthetic:port"][0].value.extensions["synthetic:extension"][
        "values"
    ] == (1,)
    with pytest.raises(TypeError):
        content.extensions["synthetic:extension"]["values"] = ()
    if record_type is not ProductDraft:
        resolved = ResolvedInput(artifact(), content)
        assert resolved.value is content


def test_all_new_values_are_frozen():
    schema = RecordSchemaRef("synthetic:record", 1)
    values = [
        schema,
        ProductProfileRef("synthetic:profile", 1),
        ResolvedInput(artifact(), record()),
        ArtifactDraft(schema, record()),
        TaskOutcome({}, ()),
    ]
    for value in values:
        field = fields(value)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, getattr(value, field))


def test_static_construction_never_opens_or_probes(monkeypatch):
    ref, content, asset = artifact(), record(), evidence()

    def forbidden(*args, **kwargs):
        pytest.fail("static construction attempted I/O or a runtime probe")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(io, "open", forbidden)
        guard.setattr(Path, "stat", forbidden)
        guard.setattr(Path, "resolve", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        schema = RecordSchemaRef("synthetic:record", 1)
        ProductProfileRef("synthetic:profile", 1)
        ResolvedInput(ref, content)
        result = TaskOutcome(
            {"synthetic:port": [ArtifactDraft(schema, content)]}, [asset]
        )
    assert result.evidence == (asset,)


def test_operations_imports_only_static_dependencies_without_side_effects():
    # ADR0013 adds these operation interfaces, not a universal plugin family.
    allowed_protocols = {
        "ProbeContext",
        "PreparedExecution",
        "OperationHandler",
        "InputCodec",
        "OutputCodec",
        "PortValidator",
    }
    # Preserve existing static modules; new dependencies are symbol-specific.
    existing_modules = {
        "collections.abc",
        "dataclasses",
        "types",
        "typing",
        "insarforge.contracts.identity",
        "insarforge.contracts.plugins",
        "insarforge.contracts.records",
        "insarforge.contracts.values",
        "insarforge.products.assets",
        "insarforge.products.models",
    }
    added_imports = {
        "inspect": {"getattr_static"},
        "insarforge.contracts.context": {"ExecutionContext", "ResourceAllocation"},
        "insarforge.products.semantics": {"SemanticValue"},
        "insarforge.products.validation": {"ProductValidationReport"},
    }

    def assert_static_boundary(source):
        tree = ast.parse(source)
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0
                assert node.module in existing_modules or node.module in added_imports
                if node.module in added_imports:
                    assert {alias.name for alias in node.names} <= added_imports[
                        node.module
                    ]
                for alias in node.names:
                    assert alias.name != "*"
                    imported[alias.asname or alias.name] = (
                        node.module + "." + alias.name
                    )
            elif isinstance(node, ast.Import):
                assert all(alias.name in existing_modules for alias in node.names)
                for alias in node.names:
                    imported[alias.asname or alias.name] = alias.name

        def base_name(base):
            if isinstance(base, ast.Subscript):
                return base_name(base.value)
            if isinstance(base, ast.Name):
                return imported.get(base.id, base.id)
            if isinstance(base, ast.Attribute):
                return base_name(base.value) + "." + base.attr
            return ""

        declared_protocols = set()
        forbidden_names = {
            "Plugin",
            "PluginProtocol",
            "BasePlugin",
            "handler_id",
            "codec_id",
            "TaskSpec",
            "WorkflowPlan",
            "Scheduler",
            "CacheStore",
            "StateStore",
            "getattr",
            "__import__",
            "eval",
            "exec",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name not in forbidden_names
                bases = {base_name(base) for base in node.bases}
                assert not bases & {"ABC", "abc.ABC"}
                if bases & ({"typing.Protocol"} | allowed_protocols):
                    declared_protocols.add(node.name)
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        assert member.name not in {"run", "execute"}
                        if member.name == "invoke":
                            assert node.name == "OperationHandler"
            elif isinstance(node, ast.Name):
                assert node.id not in forbidden_names
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_names | {"import_module"}
            elif isinstance(node, ast.arg):
                assert node.arg not in {"handler_id", "codec_id"}
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in {"handler_id", "codec_id"}
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "prepare",
                    "invoke",
                    "decode",
                    "encode",
                    "validate",
                    "validate_spec",
                }
        assert declared_protocols == allowed_protocols

    source = Path(operations.__file__).read_text()
    assert_static_boundary(source)
    # Demonstrate that the allowlist still rejects forbidden additions.
    for addition in (
        "\nclass ExtraProtocol(Protocol): pass\n",
        "\nclass ExtraProtocol(InputCodec): pass\n",
        "\nclass Plugin(Protocol): pass\n",
        "\nclass BadBusiness:\n    def run(self): pass\n",
        "\nclass BadBusiness:\n    def invoke(self): pass\n",
        "\nhandler_id = 'synthetic:handler'\n",
        "\ncodec_id = 'synthetic:codec'\n",
        "\ngetattr(plugin, operation)()\n",
        "\n__import__('synthetic.adapter')\n",
        "\nfrom insarforge.products.validation import validate_product_structure\n",
        "\nfrom inspect import getmembers\n",
    ):
        with pytest.raises(AssertionError):
            assert_static_boundary(source + addition)
    for module in (
        "insarforge.runtime",
        "insarforge.workflow",
        "insarforge.core.scheduler",
        "insarforge.core.cache",
        "insarforge.core.retry",
        "insarforge.core.state",
        "insarforge.core.resume",
        "insarforge.provenance",
        "insarforge.processors",
        "subprocess",
        "os",
        "importlib",
        "osgeo",
        "numpy",
        "xarray",
    ):
        with pytest.raises(AssertionError):
            assert_static_boundary(source + "\nimport " + module + "\n")
    code = """
import importlib.abc
import sys

class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith((
            "insarforge.core.registry", "insarforge.contracts.execution",
            "insarforge.core.scheduler", "insarforge.core.cache",
            "insarforge.core.retry", "insarforge.core.state", "insarforge.core.resume",
            "insarforge.runtime", "insarforge.workflow", "insarforge.provenance",
            "insarforge.missions", "insarforge.providers", "insarforge.processors",
            "insarforge.corrections", "insarforge.analyzers", "insarforge.qc",
            "insarforge.config", "pydantic", "yaml", "osgeo", "numpy", "xarray",
        )):
            raise AssertionError("forbidden dependency: " + fullname)

sys.meta_path.insert(0, BlockRuntime())
from insarforge.contracts import operations
assert operations.ArtifactDraft.__module__ == "insarforge.contracts.operations"
"""
    result = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True
    )
    assert result.stdout == result.stderr == ""
