"""P4.2-02 semantic propagation and explicit evidence boundaries."""

import hashlib
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from insarforge.contracts.context import ResourceAllocation, ResourceRequest
from insarforge.contracts.errors import ContractError
from insarforge.contracts.execution import (
    CachePolicy,
    OutputDeclaration,
    OutputRef,
    RetryPolicy,
    TaskSpec,
    WorkflowPlan,
)
from insarforge.contracts.fingerprints import FingerprintResult, unresolved
from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.operations import (
    InputPortContract,
    OperationBinding,
    OutputPortContract,
    ProductProfileRef,
    RecordSchemaRef,
)
from insarforge.contracts.records import (
    AccessStatus,
    AcquisitionMetadata,
    CatalogEntry,
    CatalogSnapshot,
    ProviderAvailability,
    ProviderDelivery,
    QCReport,
    QCStatus,
)
from insarforge.contracts.values import ArtifactRef, freeze_json
from insarforge.core.cache import (
    AssetEvidence,
    CacheCandidate,
    CachedOutput,
    CommitEvidence,
    can_publish_cache,
    validate_cache_candidate,
)
from insarforge.core.content_identity import (
    code_content_identity,
    engine_code_identity,
    verify_asset_content,
)
from insarforge.core.fingerprints import (
    execution_identity,
    input_identities,
    task_fingerprint,
)
from insarforge.core.result_identity import artifact_semantic_digest
from insarforge.products.assets import (
    AssetIntegrity,
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.directory_manifest import (
    DirectoryMember,
    DirectoryMemberManifest,
)
from insarforge.products.directory_manifest_serialization import (
    directory_member_manifest_to_bytes,
)
from insarforge.products.models import LineageEntry, ProducerRef, Product, ProductionRef
from insarforge.products.semantics import SemanticStatus, SemanticValue
from insarforge.products.serialization import product_to_manifest_bytes
from insarforge.products.validation import (
    ProductValidationReport,
    ValidationIssue,
    ValidationIssueKind,
    validate_product_structure,
)


def h(value):
    return hashlib.sha256(
        value.encode() if isinstance(value, str) else value
    ).hexdigest()


def strong(value):
    return FingerprintResult(h(value), True)


def known(value):
    return SemanticValue(SemanticStatus.KNOWN, freeze_json(value), None, ())


def ref(name="a", digest=None):
    return ArtifactRef(
        name,
        "insarforge:product",
        2,
        h(name) if digest is None else digest,
        h("manifest"),
        "synthetic:input",
    )


@dataclass(frozen=True)
class Prepared:
    semantic_execution_identity: SemanticValue
    preparation: object = field(default_factory=lambda: freeze_json({}))


def prepared(**changes):
    return Prepared(
        known(
            dict(
                schema_version=1,
                wrapper_digest=h("wrapper"),
                native_components={
                    "native": {
                        "executable_digest": h("binary"),
                        "dependency_digests": {"runtime": h("runtime")},
                    }
                },
                settings={"precision": "double", "threads": 1, "seed": 0},
                external_resource_digests={"calibration": h("calibration")},
            )
            | changes
        )
    )


class Codec:
    def decode(self, *args):
        pytest.fail("decoder must not run")

    def encode(self, *args):
        pytest.fail("encoder must not run")


class Validator:
    def validate(self, value, schema, profile):
        if isinstance(value, Product):
            return validate_product_structure(value)
        return ProductValidationReport(())


class Handler:
    def validate_spec(self, parameters, inputs, outputs):
        return ProductValidationReport(())

    def prepare(self, *args):
        pytest.fail("native preparation must not run")

    def invoke(self, *args):
        pytest.fail("execution must not run")


SCHEMA = RecordSchemaRef("insarforge:product", 2)
PROFILE = ProductProfileRef("profile:test", 1)
PLUGIN = PluginRef(PluginKind.PROCESSOR, "synthetic:processor", 1)
ALLOCATION = ResourceAllocation(1, None, 0)


def binding(ports=("in",)):
    return OperationBinding(
        "synthetic:op",
        1,
        "synthetic:parameters",
        1,
        tuple(
            InputPortContract(p, SCHEMA, PROFILE, 0, None, Codec(), Validator())
            for p in ports
        ),
        (OutputPortContract("out", SCHEMA, PROFILE, 1, Codec(), Validator()),),
        (),
        1,
        Handler(),
    )


def task(inputs=None, **changes):
    return TaskSpec(
        **(
            dict(
                schema_version=1,
                task_id="task:a",
                plugin_ref=PLUGIN,
                operation_id="synthetic:op",
                operation_api_version=1,
                inputs={"in": (ref(),)} if inputs is None else inputs,
                outputs=(
                    OutputDeclaration(
                        "out", "insarforge:product", 2, 1, "profile:test", 1
                    ),
                ),
                semantic_parameters={"alpha": 1, "beta": [2, 3]},
                resources=ResourceRequest(),
            )
            | changes
        )
    )


def recipe(t=None, b=None, **changes):
    t = t or task()
    return task_fingerprint(
        t,
        b or binding(tuple(t.inputs)),
        **(
            dict(
                core_semantics_revision="core:v1",
                engine_identity=strong("engine"),
                implementation_identity=strong("implementation"),
                prepared=prepared(),
                allocation=ALLOCATION,
                resolved_inputs=t.inputs,
            )
            | changes
        ),
    )


def product(t=None, r=None, execution=None, assets=(), **changes):
    t = t or task()
    r = r or recipe(t)
    execution = execution or execution_identity(prepared(), ALLOCATION)
    return Product(
        **(
            dict(
                schema_id="insarforge:product",
                schema_version=2,
                product_id="product:one",
                product_kind="product:test",
                profile_id="profile:test",
                profile_version=1,
                assets=assets,
                layers=(),
                geometries=(),
                acquisition_refs=(),
                semantic_metadata={"value": known(1)},
                extensions={},
                producer=ProducerRef(
                    t.plugin_ref,
                    "1.0",
                    known(h("implementation")),
                    known(execution.value),
                ),
                produced_by=ProductionRef(known(r.value), "out", "attempt:one"),
                lineage=tuple(
                    LineageEntry(p, a) for p in sorted(t.inputs) for a in t.inputs[p]
                ),
                provenance_ref="synthetic:provenance",
            )
            | changes
        )
    )


def result(p=None, t=None, r=None, assets=None):
    t = t or task()
    return artifact_semantic_digest(
        p or product(t),
        producer_fingerprint=r or recipe(t),
        output_port="out",
        ordered_inputs=t.inputs,
        asset_content_identities=assets or {},
    )


def candidate(p=None, t=None, evidence=()):
    t = t or task()
    p = p or product(t)
    r = recipe(t)
    raw = product_to_manifest_bytes(p)
    ar = ArtifactRef(
        p.product_id,
        p.schema_id,
        p.schema_version,
        result(p, t, r, {a.asset.asset_id: a.identity.value for a in evidence}).value,
        h(raw),
        "synthetic:manifest",
    )
    output = CachedOutput(ar, raw, evidence)
    return CacheCandidate(
        1,
        r.value,
        execution_identity(prepared(), ALLOCATION).value,
        input_identities(t.inputs),
        {"out": [output]},
        CommitEvidence(h("receipt"), {"out": [h(raw)]}),
    )


def decide(c=None, t=None, b=None, **changes):
    t = t or task()
    return validate_cache_candidate(
        t,
        b or binding(tuple(t.inputs)),
        recipe(t),
        execution_identity(prepared(), ALLOCATION),
        t.inputs,
        c or candidate(t=t),
        **changes,
    )


def changed_output(c, **changes):
    output = replace(c.outputs["out"][0], **changes)
    return replace(
        c,
        outputs={"out": (output,)},
        commit=CommitEvidence(
            h("receipt"), {"out": (output.artifact.manifest_digest,)}
        ),
    )


def test_deterministic_and_instance_independent():
    t = task()
    expected = recipe(t)
    assert expected.reusable and len(expected.value) == 64
    other = replace(
        t,
        task_id="task:other",
        semantic_parameters={"beta": [2, 3], "alpha": 1},
        resources=ResourceRequest(9, 123, 2),
        retry_policy=RetryPolicy(3, 5),
        cache_policy=CachePolicy.DISABLED,
    )
    assert recipe(other) == expected
    moved = replace(
        ref(),
        record_id="record:other",
        manifest_digest=h("other"),
        locator="synthetic:elsewhere",
    )
    assert recipe(replace(t, inputs={"in": (moved,)})) == expected
    assert (
        recipe(
            t,
            prepared=replace(
                prepared(), preparation=freeze_json({"temporary": "unused"})
            ),
        )
        == expected
    )
    assert recipe(t, allocation=ResourceAllocation(1, 1024, 0)) == expected
    assert recipe(task({"z": (ref("b"),), "in": (ref(),)})) == recipe(
        task({"in": (ref(),), "z": (ref("b"),)})
    )


@pytest.mark.parametrize(
    "component",
    [
        "parameters",
        "validator",
        "operation",
        "plugin",
        "engine",
        "implementation",
        "core",
        "cpu",
        "gpu",
        "input",
        "outputs",
    ],
)
def test_recipe_semantic_changes(component):
    t, b, args = task(), binding(), {}
    if component == "parameters":
        t = replace(t, semantic_parameters={"alpha": 2})
    elif component == "validator":
        b = replace(b, validator_revision=2)
    elif component == "operation":
        t, b = replace(t, operation_api_version=2), replace(b, operation_api_version=2)
    elif component == "plugin":
        t = replace(t, plugin_ref=replace(PLUGIN, api_version=2))
    elif component in ("engine", "implementation"):
        args[component + "_identity"] = strong("changed")
    elif component == "core":
        args["core_semantics_revision"] = "core:v2"
    elif component == "cpu":
        args["allocation"] = ResourceAllocation(2, None, 0)
    elif component == "gpu":
        args["allocation"] = ResourceAllocation(1, None, 1)
    elif component == "input":
        t = task({"in": (ref("changed"),)})
    else:
        t = replace(t, outputs=(replace(t.outputs[0], count=2),))
        b = replace(b, outputs=(replace(b.outputs[0], count=2),))
    assert recipe(t, b, **args) != recipe()


@pytest.mark.parametrize(
    "component",
    ["wrapper_digest", "native_components", "settings", "external_resource_digests"],
)
def test_execution_semantic_changes(component):
    changes = {
        "wrapper_digest": h("new wrapper"),
        "native_components": {
            "native": {
                "executable_digest": h("binary"),
                "dependency_digests": {"runtime": h("new runtime")},
            }
        },
        "settings": {"precision": "single", "threads": 2, "seed": 1},
        "external_resource_digests": {"calibration": h("new calibration")},
    }
    assert recipe(prepared=prepared(**{component: changes[component]})) != recipe()


def test_order_roles_repetition():
    a, b = ref(), ref("b")
    assert recipe(task({"in": (a, b)})) != recipe(task({"in": (b, a)}))
    assert recipe(task({"in": (a, a)})) != recipe(task({"in": (a,)}))
    assert recipe(task({"left": (a,)})) != recipe(task({"right": (a,)}))


@pytest.mark.parametrize("weak", [None, "", "UNKNOWN", "semantic:placeholder"])
def test_weak_input_no_fake_hash(weak):
    # ArtifactRef's frozen constructor rejects empty strings; None/placeholders
    # are legal references, but never strong cache identities.
    if weak == "":
        with pytest.raises(ValueError):
            replace(ref(), semantic_digest=weak)
        return
    r = recipe(task({"in": (replace(ref(), semantic_digest=weak),)}))
    assert r.value is None and not r.reusable and "INPUT_IDENTITY_WEAK" in r.reasons


@pytest.mark.parametrize(
    "changes",
    [
        {"wrapper_digest": "version:1"},
        {
            "native_components": {
                "native": {
                    "executable_digest": "path:/native",
                    "dependency_digests": {},
                }
            }
        },
        {"native_components": {"native": {"executable_digest": h("binary")}}},
        {"external_resource_digests": {"resource": None}},
        {"schema_version": True},
    ],
)
def test_incomplete_execution_is_not_reusable(changes):
    assert not recipe(prepared=prepared(**changes)).reusable


def test_unknown_and_weak_code_identity():
    unknown = Prepared(
        SemanticValue(SemanticStatus.UNKNOWN, None, "native:unknown", ())
    )
    assert not recipe(prepared=unknown).reusable
    for key in ("engine_identity", "implementation_identity"):
        r = recipe(**{key: unresolved("CONTENT_UNAVAILABLE")})
        assert r.value is None and r.reasons
    with pytest.raises(ContractError):
        FingerprintResult(h("fake"), False, ("WEAK",))


def test_explicit_code_scope_and_engine_scope(tmp_path):
    root = tmp_path / "package"
    root.mkdir()
    (root / "__init__.py").write_text("# package")
    for name in ("core", "contracts", "products", "plugins", "tests", "docs"):
        (root / name).mkdir()
        (root / name / "a.py").write_text("value = 1")
    initial = engine_code_identity(root)
    assert initial.reusable
    for name in ("plugins", "tests", "docs"):
        (root / name / "a.py").write_text("changed unrelated material")
    assert engine_code_identity(root) == initial
    (root / "core" / "a.py").write_text("value = 2")
    assert engine_code_identity(root) != initial
    f = root / "plugins" / "a.py"
    copy = tmp_path / "same.py"
    copy.write_bytes(f.read_bytes())
    assert code_content_identity({"implementation.py": f}) == code_content_identity(
        {"implementation.py": copy}
    )
    assert not code_content_identity({"missing.py": root / "absent"}).reusable
    assert not code_content_identity({}).reusable
    with pytest.raises(ContractError, match="CODE_LOGICAL_NAME"):
        code_content_identity({"../bad": f})


def test_actual_result_changes_not_recipe():
    p = product()
    d = result(p)
    assert d.reusable and d.value != recipe().value
    assert result(replace(p, semantic_metadata={"value": known(2)})) != d
    assert (
        result(
            replace(
                p,
                product_id="product:other",
                provenance_ref="synthetic:other",
                produced_by=replace(p.produced_by, attempt_id="attempt:other"),
                producer=replace(
                    p.producer, implementation_version="provenance version"
                ),
            )
        )
        == d
    )
    assert not result(
        replace(p, acquisition_refs=(replace(ref(), semantic_digest=None),))
    ).reusable
    assert not artifact_semantic_digest(
        p,
        producer_fingerprint=unresolved("UNKNOWN"),
        output_port="out",
        ordered_inputs=task().inputs,
        asset_content_identities={},
    ).reusable


def file_asset(path, content=b"old"):
    path.write_bytes(content)
    return NativeAsset(
        "asset:one",
        AssetKind.FILE,
        AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, str(path), None),
        None,
        len(content),
        AssetIntegrity("sha256", h(content)),
        None,
    )


def test_file_same_size_restored_mtime_and_cache_refusal(tmp_path):
    path = tmp_path / "data"
    a = file_asset(path)
    good = verify_asset_content(a)
    p = product(assets=(a,))
    c = candidate(p, evidence=(AssetEvidence(a, good),))
    assert decide(c).accepted
    stat = path.stat()
    path.write_bytes(b"new")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    bad = verify_asset_content(a)
    assert not bad.reusable
    assert not decide(changed_output(c, assets=(AssetEvidence(a, bad),))).accepted
    newer = replace(a, integrity=AssetIntegrity("sha256", h(b"new")))
    assert verify_asset_content(newer).reusable
    assert result(p, assets={a.asset_id: good.value}) != result(
        p, assets={a.asset_id: h(b"new")}
    )
    relocated = replace(
        a, location=replace(a.location, value=str(tmp_path / "elsewhere"))
    )
    assert result(
        replace(p, assets=(relocated,)), assets={a.asset_id: good.value}
    ) == result(p, assets={a.asset_id: good.value})
    path.unlink()
    assert not verify_asset_content(a).reusable


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "parent"])
def test_file_no_link_following(tmp_path, attack):
    f = tmp_path / "data"
    a = file_asset(f)
    if attack == "hardlink":
        os.link(f, tmp_path / "alias")
    elif attack == "symlink":
        moved = tmp_path / "actual"
        f.rename(moved)
        f.symlink_to(moved)
    else:
        folder = tmp_path / "directory"
        folder.mkdir()
        f.rename(folder / "data")
        alias = tmp_path / "alias"
        alias.symlink_to(folder, target_is_directory=True)
        a = replace(a, location=replace(a.location, value=str(alias / "data")))
    assert not verify_asset_content(a).reusable


def directory_asset(root):
    root.mkdir()
    (root / "data").write_bytes(b"old")
    manifest = DirectoryMemberManifest(
        1,
        (
            DirectoryMember(
                "data", AssetKind.FILE, 3, AssetIntegrity("sha256", h(b"old"))
            ),
        ),
    )
    raw = directory_member_manifest_to_bytes(manifest)
    reference = ArtifactRef(
        "members",
        "insarforge:directory-member-manifest",
        1,
        None,
        h(raw),
        "synthetic:members",
    )
    a = NativeAsset(
        "asset:one",
        AssetKind.DIRECTORY,
        AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, str(root), None),
        None,
        None,
        None,
        reference,
    )
    return a, raw


@pytest.mark.parametrize("mutation", ["addition", "removal", "replacement"])
def test_directory_members_and_cache_refusal(tmp_path, mutation):
    root = tmp_path / "members"
    a, raw = directory_asset(root)
    good = verify_asset_content(a, member_manifest_bytes=raw)
    assert good.reusable
    c = candidate(product(assets=(a,)), evidence=(AssetEvidence(a, good),))
    assert decide(c).accepted
    if mutation == "addition":
        (root / "extra").write_bytes(b"other")
    elif mutation == "removal":
        (root / "data").unlink()
    else:
        f = root / "data"
        before = f.stat()
        f.write_bytes(b"new")
        os.utime(f, ns=(before.st_atime_ns, before.st_mtime_ns))
    bad = verify_asset_content(a, member_manifest_bytes=raw)
    assert not bad.reusable
    assert not decide(changed_output(c, assets=(AssetEvidence(a, bad),))).accepted


def test_directory_manifest_integrity_and_safe_corruption(tmp_path):
    a, raw = directory_asset(tmp_path / "members")
    assert not verify_asset_content(a).reusable
    assert not verify_asset_content(a, member_manifest_bytes=raw + b" ").reusable
    corrupt = b'{"schema_version":1,"schema_version":2}'
    a = replace(
        a,
        member_manifest_ref=replace(a.member_manifest_ref, manifest_digest=h(corrupt)),
    )
    with pytest.raises(ContractError, match="DIRECTORY_MANIFEST_INVALID"):
        verify_asset_content(a, member_manifest_bytes=corrupt)


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("recipe", "CACHE_RECIPE_MISMATCH"),
        ("execution", "CACHE_EXECUTION_MISMATCH"),
        ("inputs", "CACHE_INPUT_MISMATCH"),
        ("commit", "CACHE_UNCOMMITTED"),
        ("ports", "CACHE_OUTPUT_PORTS"),
        ("count", "CACHE_OUTPUT_COUNT"),
        ("bytes", "CACHE_MANIFEST_DIGEST"),
        ("schema", "CACHE_SCHEMA"),
        ("semantic", "CACHE_RESULT_IDENTITY"),
        ("receipt", "CACHE_COMMIT_OUTPUTS"),
    ],
)
def test_cache_rejects_incompatible_candidate(mutation, code):
    c = candidate()
    assert decide(c).accepted
    if mutation == "recipe":
        c = replace(c, fingerprint=h("wrong"))
    elif mutation == "execution":
        c = replace(c, execution_identity=h("wrong"))
    elif mutation == "inputs":
        c = replace(c, input_semantics=input_identities({"in": (ref("wrong"),)}))
    elif mutation == "commit":
        c = replace(c, commit=None)
    elif mutation == "ports":
        c = replace(c, outputs={})
    elif mutation == "count":
        c = replace(c, outputs={"out": ()})
    elif mutation == "bytes":
        c = changed_output(c, manifest_bytes=b"bad")
    elif mutation == "receipt":
        c = replace(c, commit=CommitEvidence(h("receipt"), {"out": (h("other"),)}))
    else:
        ar = c.outputs["out"][0].artifact
        ar = replace(
            ar,
            **(
                {"schema_id": "other:schema"}
                if mutation == "schema"
                else {"semantic_digest": h("wrong")}
            ),
        )
        c = changed_output(c, artifact=ar)
    assert decide(c).reasons == (code,)


@pytest.mark.parametrize(
    "raw",
    [b"{}", b'{"schema_id":1,"schema_id":2}', b'{"value":NaN}', b"not json", b"\xff"],
)
def test_cache_corrupt_manifest_safe_rejection(raw):
    c = candidate()
    c = changed_output(
        c,
        manifest_bytes=raw,
        artifact=replace(c.outputs["out"][0].artifact, manifest_digest=h(raw)),
    )
    d = decide(c)
    assert not d.accepted
    assert all(code.startswith("CACHE_") for code in d.reasons)


def test_profile_producer_and_weak_assets():
    p = product()
    assert decide(candidate(replace(p, profile_id="profile:other"))).reasons == (
        "CACHE_PROFILE",
    )
    assert decide(
        candidate(
            replace(
                p,
                producer=replace(
                    p.producer, plugin=replace(PLUGIN, plugin_id="synthetic:other")
                ),
            )
        )
    ).reasons == ("CACHE_PRODUCT_PRODUCER",)
    assert not decide(
        candidate(
            replace(
                p,
                produced_by=replace(p.produced_by, task_fingerprint=known(h("wrong"))),
            )
        )
    ).accepted
    with pytest.raises(ContractError):
        replace(candidate(), schema_version=True)
    with pytest.raises(ContractError):
        replace(
            candidate(),
            input_semantics=[{"port": "in", "semantic_digests": ["UNKNOWN"]}],
        )


def test_cache_is_pure_and_disabled_still_has_result_identity(monkeypatch):
    c = candidate()

    def forbidden(*args, **kwargs):
        pytest.fail("pure decision attempted filesystem/network access")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    assert decide(c).accepted
    t = replace(task(), cache_policy=CachePolicy.DISABLED)
    assert recipe(t).reusable and result(t=t).reusable
    assert not can_publish_cache(t.cache_policy, recipe(t))
    assert not decide(c, t).accepted
    assert not can_publish_cache(CachePolicy.AUTO, unresolved("WEAK"))


def test_weak_validation_report_refuses_cache_and_recipe():
    class Unverified(Validator, Handler):
        def validate(self, *args):
            return ProductValidationReport(
                (
                    ValidationIssue(
                        ValidationIssueKind.UNVERIFIED, "test:unknown", "out", {}
                    ),
                )
            )

        def validate_spec(self, *args):
            return self.validate()

    b = binding()
    assert not recipe(b=replace(b, handler=Unverified())).reusable
    assert not decide(
        b=replace(b, outputs=(replace(b.outputs[0], validator=Unverified()),))
    ).accepted


def test_immutable_evidence_snapshots():
    c = candidate()
    outputs = {"out": list(c.outputs["out"])}
    copied = replace(c, outputs=outputs)
    outputs["out"].clear()
    assert len(copied.outputs["out"]) == 1
    with pytest.raises(TypeError):
        copied.outputs["extra"] = ()
    assert decide(copied).accepted


@pytest.mark.parametrize("kind", ["catalog", "acquisition", "qc"])
def test_typed_records_result_identity(kind):
    a = ref()
    if kind == "catalog":
        p = CatalogSnapshot(
            "catalog:one",
            "insarforge:catalog",
            1,
            PluginRef(PluginKind.PROVIDER, "synthetic:provider", 1),
            "query:test",
            1,
            {"scene": "A"},
            (
                CatalogEntry(
                    "entry:one",
                    AccessStatus(
                        ProviderAvailability.AVAILABLE,
                        ProviderDelivery.DIRECT,
                        True,
                        None,
                    ),
                    {},
                    (a,),
                ),
            ),
            {},
        )
        changed = replace(p, selectors={"scene": "B"})
        weak = replace(
            p,
            entries=(
                replace(
                    p.entries[0], evidence_refs=(replace(a, semantic_digest=None),)
                ),
            ),
        )
    elif kind == "acquisition":
        p = AcquisitionMetadata(
            "acquisition:one",
            "insarforge:acquisition",
            1,
            a,
            PluginRef(PluginKind.MISSION, "synthetic:mission", 1),
            {"orbit": known(1)},
            (),
            {},
        )
        changed = replace(p, attributes={"orbit": known(2)})
        weak = replace(p, source_ref=replace(a, semantic_digest=None))
    else:
        p = QCReport(
            "qc:one",
            "insarforge:qc",
            1,
            QCStatus.PASS,
            "method:test",
            "1",
            (a,),
            (),
            (),
            {},
        )
        changed = replace(p, status=QCStatus.FAIL)
        weak = replace(p, input_refs=(replace(a, semantic_digest=None),))
    assert result(p).reusable
    assert result(p) == result(replace(p, record_id="record:other"))
    assert result(p) != result(changed)
    assert not result(weak).reusable


def test_local_chain_invalidation_and_plan_digest_independence():
    upstream = task(inputs={"in": ()}, task_id="upstream")
    independent = task(inputs={"in": ()}, task_id="independent")
    downstream = task(
        inputs={"in": (OutputRef("upstream", "out"),)}, task_id="downstream"
    )
    original_plan = WorkflowPlan(1, (upstream, independent, downstream))
    up_recipe = recipe(upstream)
    actual = result(product(upstream), upstream, up_recipe)
    resolved = {"in": (ref("upstream-output", actual.value),)}
    old_down = recipe(downstream, resolved_inputs=resolved)
    for change in ("parameter", "execution", "actual"):
        changed = (
            replace(upstream, semantic_parameters={"alpha": 9})
            if change == "parameter"
            else upstream
        )
        new_recipe = (
            recipe(changed, prepared=prepared(wrapper_digest=h("changed")))
            if change == "execution"
            else recipe(changed)
        )
        new_product = (
            product(changed, new_recipe, semantic_metadata={"value": known(99)})
            if change == "actual"
            else product(changed, new_recipe)
        )
        new_actual = result(new_product, changed, new_recipe)
        assert new_actual != actual
        assert (
            recipe(
                downstream,
                resolved_inputs={"in": (ref("upstream-output", new_actual.value),)},
            )
            != old_down
        )
        assert recipe(independent) == recipe(replace(independent, task_id="renamed"))
        if change == "actual":
            assert new_recipe == up_recipe
        if change == "parameter":
            new_plan = WorkflowPlan(1, (changed, independent, downstream))
            assert new_plan.digest != original_plan.digest
    reordered = WorkflowPlan(1, (downstream, independent, upstream))
    assert reordered.digest == original_plan.digest


def test_safe_domain_failures_and_missing_assets(tmp_path):
    with pytest.raises(ContractError, match="RECIPE_INPUTS"):
        recipe(resolved_inputs=None)
    with pytest.raises(ContractError, match="PERSISTENCE_SECRET") as error:
        recipe(prepared=prepared(settings={"password": "do-not-echo"}))
    assert "do-not-echo" not in str(error.value)
    with pytest.raises(ContractError):
        recipe(task({"in": (ref(),)}), resolved_inputs={"in": (object(),)})
    with pytest.raises(ContractError):
        recipe(b=replace(binding(), outputs=()))
    a = file_asset(tmp_path / "file")
    c = candidate(
        product(assets=(a,)), evidence=(AssetEvidence(a, verify_asset_content(a)),)
    )
    assert decide(changed_output(c, assets=())).reasons == ("CACHE_ASSETS_MISSING",)
    assert not verify_asset_content(replace(a, integrity=None)).reusable
    remote = replace(
        a,
        location=AssetLocation(
            AssetLocationKind.REMOTE_REFERENCE, "https://example.invalid/asset", None
        ),
    )
    assert not verify_asset_content(remote).reusable


def test_cache_non_product_explicit_decoder():
    p = QCReport(
        "qc:one", "insarforge:qc", 1, QCStatus.PASS, "method:test", "1", (), (), (), {}
    )
    schema = RecordSchemaRef(p.schema_id, p.schema_version)
    t = task(outputs=(OutputDeclaration("out", p.schema_id, p.schema_version),))
    b = replace(
        binding(),
        outputs=(OutputPortContract("out", schema, None, 1, Codec(), Validator()),),
    )
    r = recipe(t, b)
    raw = b'{"record_id":"qc:one","schema_id":"insarforge:qc","schema_version":1,"status":"pass","method_id":"method:test","method_version":"1","input_refs":[],"metrics":[],"findings":[],"extensions":{}}'
    digest = artifact_semantic_digest(
        p,
        producer_fingerprint=r,
        output_port="out",
        ordered_inputs=t.inputs,
        asset_content_identities={},
    )
    output = CachedOutput(
        ArtifactRef(p.record_id, p.schema_id, 1, digest.value, h(raw), "synthetic:qc"),
        raw,
    )
    c = CacheCandidate(
        1,
        r.value,
        execution_identity(prepared(), ALLOCATION).value,
        input_identities(t.inputs),
        {"out": (output,)},
        CommitEvidence(h("receipt"), {"out": (h(raw),)}),
    )
    args = (t, b, r, execution_identity(prepared(), ALLOCATION), t.inputs, c)
    assert validate_cache_candidate(*args).reasons == ("CACHE_DECODER_MISSING",)

    def decoder(artifact, payload):
        assert artifact == output.artifact and payload == raw
        return p

    assert validate_cache_candidate(*args, decode_record=decoder).accepted


def test_fingerprint_architecture_boundaries():
    import ast
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    files = [root / "src/insarforge/contracts/fingerprints.py"] + [
        root / "src/insarforge/core" / name
        for name in (
            "fingerprints.py",
            "content_identity.py",
            "result_identity.py",
            "cache.py",
        )
    ]
    forbidden = (
        "insarforge.config",
        "insarforge.missions",
        "insarforge.providers",
        "insarforge.processors",
        "insarforge.corrections",
        "insarforge.analyzers",
        "insarforge.qc",
        "pydantic",
        "numpy",
        "scipy",
        "rasterio",
        "osgeo",
    )
    for file in files:
        tree = ast.parse(file.read_text())
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            )
            assert not any(
                name == prefix or name.startswith(prefix + ".")
                for name in names
                for prefix in forbidden
            )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value.lower() not in {
                    "isce2",
                    "isce3",
                    "gamma",
                    "stamps",
                    "sentinel1",
                }
    for file in (root / "src/insarforge/products").glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("insarforge.core")
    probe = subprocess.run(
        [
            sys.executable,
            "-B",
            "-I",
            "-c",
            "import sys; import insarforge.core.cache; import insarforge.core.content_identity; "
            "assert not any(k.split('.')[0] in {'numpy','scipy','pydantic','rasterio','osgeo'} for k in sys.modules)",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr


def test_catalog_cache_boolean_access_field_is_not_a_credential():
    import json

    record = CatalogSnapshot(
        "catalog:one",
        "insarforge:catalog",
        1,
        PluginRef(PluginKind.PROVIDER, "synthetic:provider", 1),
        "query:test",
        1,
        {},
        (
            CatalogEntry(
                "entry:one",
                AccessStatus(
                    ProviderAvailability.AVAILABLE, ProviderDelivery.DIRECT, True, None
                ),
                {},
                (),
            ),
        ),
        {},
    )
    t = task(outputs=(OutputDeclaration("out", record.schema_id, 1),))
    b = replace(
        binding(),
        outputs=(
            OutputPortContract(
                "out",
                RecordSchemaRef(record.schema_id, 1),
                None,
                1,
                Codec(),
                Validator(),
            ),
        ),
    )
    r = recipe(t, b)
    digest = artifact_semantic_digest(
        record,
        producer_fingerprint=r,
        output_port="out",
        ordered_inputs=t.inputs,
        asset_content_identities={},
    )
    data = dict(
        schema_id=record.schema_id,
        schema_version=1,
        record_id=record.record_id,
        provider={
            "kind": "provider",
            "plugin_id": "synthetic:provider",
            "api_version": 1,
        },
        query_schema_id="query:test",
        query_schema_version=1,
        selectors={},
        entries=[
            {
                "entry_id": "entry:one",
                "access": {
                    "availability": "available",
                    "delivery": "direct",
                    "authentication_required": True,
                    "reason_code": None,
                },
                "attributes": {},
                "evidence_refs": [],
            }
        ],
        extensions={},
    )

    def evaluate(payload):
        raw = json.dumps(payload).encode()
        output = CachedOutput(
            ArtifactRef(
                record.record_id,
                record.schema_id,
                1,
                digest.value,
                h(raw),
                "synthetic:catalog",
            ),
            raw,
        )
        c = CacheCandidate(
            1,
            r.value,
            execution_identity(prepared(), ALLOCATION).value,
            input_identities(t.inputs),
            {"out": (output,)},
            CommitEvidence(h("receipt"), {"out": (h(raw),)}),
        )
        return validate_cache_candidate(
            t,
            b,
            r,
            execution_identity(prepared(), ALLOCATION),
            t.inputs,
            c,
            decode_record=lambda ar, raw: record,
        )

    assert evaluate(data).accepted
    data["entries"][0]["access"]["authentication_required"] = "credential-must-not-pass"
    assert not evaluate(data).accepted
    data["entries"][0]["access"]["authentication_required"] = True
    data["entries"][0]["attributes"] = {"token": "credential-must-not-pass"}
    assert not evaluate(data).accepted
