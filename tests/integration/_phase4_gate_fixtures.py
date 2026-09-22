"""Synthetic native records and family implementations for frozen Phase 4 gates."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from insarforge.contracts.plugins import (
    AcquireRequest,
    AnalysisRequest,
    CorrectionRequest,
)
from insarforge.core.registry import PluginRegistry
from insarforge.core.runtime import Runtime
from insarforge.products.assets import (
    AssetIntegrity,
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor
from insarforge.products.grid import GridDefinition
from insarforge.products.layers import DataLayer, LayerSelector
from insarforge.products.profiles import (
    LayerRequirement,
    ProductProfile,
    validate_product_profile,
)
from insarforge.products.semantics import (
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)

from ._canonical_workflow import BUDGET
from ._fake_operations import Factory, Harness, PortValidator, build_harness
from ._fake_plugins import (
    FakeAnalyzer,
    FakeCorrection,
    FakeProvider,
    business,
    draft,
    known,
)

UNKNOWN = SemanticValue(SemanticStatus.UNKNOWN, None, "synthetic:unspecified", ())


def typed(value):
    return SemanticValue(SemanticStatus.KNOWN, value, None, ())


def asset(path, identity):
    raw = path.read_bytes()
    return NativeAsset(
        identity,
        AssetKind.FILE,
        AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, str(path), None),
        "application/json",
        len(raw),
        AssetIntegrity("sha256", hashlib.sha256(raw).hexdigest()),
        None,
    )


def native_product(config, parameters, context):
    # Layout is private to this producer; consumers only use committed declarations.
    folder = (
        "private/one"
        if parameters["label"] == "synthetic:layout-one"
        else "different/deep/two"
    )
    path = context.artifact_dir / folder / "container.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"a": "toy-A", "b": "toy-B"}), encoding="utf-8")
    native = asset(path, "synthetic:container")
    layers, geometries = [], []
    for name in ("a", "b"):
        unit = typed(UnitSpec("synthetic:unit-" + name, "synthetic:quantity", None))
        geometry_id = "synthetic:geometry-" + name
        geometries.append(
            GeometryDescriptor(
                geometry_id,
                "synthetic:domain",
                typed("synthetic:coordinates"),
                (
                    AxisDescriptor(
                        "synthetic:axis",
                        "synthetic:axis-role",
                        unit,
                        typed("synthetic:direction"),
                    ),
                ),
                (2,),
                typed(
                    GridDefinition("synthetic:grid-" + name, {"synthetic:marker": name})
                ),
                typed("synthetic:registration"),
                UNKNOWN,
            )
        )
        sign = (
            UNKNOWN
            if parameters["label"] == "synthetic:unknown-sign"
            else typed(
                SignSpec(
                    "synthetic:sign",
                    "synthetic:observable",
                    "synthetic:direction",
                    None,
                    None,
                    (),
                )
            )
        )
        layers.append(
            DataLayer(
                "synthetic:layer-" + name,
                "synthetic:role",
                native.asset_id,
                LayerSelector("synthetic:json-key", name),
                typed("synthetic:quantity"),
                unit,
                sign,
                typed(geometry_id),
                UNKNOWN,
                ("synthetic:axis",),
            )
        )
    return replace(
        draft(config, "acquire", parameters),
        assets=(native,),
        layers=tuple(layers),
        geometries=tuple(geometries),
    )


def observe(product):
    """Read bytes through the formal Product; no knowledge of producer layout."""
    observations = []
    for layer in product.layers:
        native = next(a for a in product.assets if a.asset_id == layer.asset_id)
        geometry = next(
            g for g in product.geometries if g.geometry_id == layer.geometry_ref.value
        )
        payload = json.loads(Path(native.location.value).read_text(encoding="utf-8"))
        observations.append(
            {
                "layer": layer.layer_id,
                "selector": layer.selector.selector_string,
                "unit": layer.unit.value.unit_id,
                "grid": geometry.grid_definition.value.format_id,
                "payload": payload[layer.selector.selector_string],
            }
        )
    return observations


class NativeProvider(FakeProvider):
    def acquire(self, request, context):
        result = native_product(self.config, request.parameters, context)
        return business(
            self.journal, "acquire", AcquireRequest, request, context, result
        )


class ManifestAnalyzer(FakeAnalyzer):
    def analyze(self, request, context):
        observations = observe(request.product_inputs["source"][0].value)
        result = replace(
            draft(self.config, "analyze", request.parameters),
            semantic_metadata={"synthetic:observations": known(observations)},
        )
        return business(
            self.journal, "analyze", AnalysisRequest, request, context, (result,)
        )


class LayerCorrection(FakeCorrection):
    def correct(self, request, context):
        source = request.source_inputs["source"][0].value
        if request.parameters["label"] == "synthetic:alias":
            corrected = replace(source.assets[0], asset_id="synthetic:corrected")
        else:
            path = context.artifact_dir / "corrected.json"
            path.write_text(
                json.dumps({"a": "corrected:" + observe(source)[0]["payload"]}),
                encoding="utf-8",
            )
            corrected = asset(path, "synthetic:corrected")
        layer = replace(
            source.layers[0],
            layer_id="synthetic:corrected-layer",
            asset_id=corrected.asset_id,
        )
        result = replace(
            draft(self.config, "correct", request.parameters),
            assets=source.assets + (corrected,),
            layers=source.layers + (layer,),
            geometries=source.geometries,
        )
        return business(
            self.journal, "correct", CorrectionRequest, request, context, (result,)
        )


class KnownSignValidator(PortValidator):
    def validate(self, value, schema, profile):
        structural = super().validate(value, schema, profile)
        if not structural.is_fully_verified:
            return structural
        requirement = LayerRequirement(
            "synthetic:known-sign",
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            True,
            False,
            2,
            2,
            {},
        )
        return validate_product_profile(
            value,
            ProductProfile("synthetic:profile", 1, (), (), (), (requirement,), {}),
        )


def composition(*, require_sign=False):
    original = build_harness()
    registry = PluginRegistry(required_api_version=1)
    implementation = {
        name: Path(__file__).with_name(name)
        for name in (
            "__init__.py",
            "_fake_plugins.py",
            "_fake_operations.py",
            Path(__file__).name,
        )
    }
    digest = hashlib.sha256(
        b"".join(
            name.encode() + b"\0" + path.read_bytes()
            for name, path in sorted(implementation.items())
        )
    ).hexdigest()
    replacements = {
        FakeProvider: NativeProvider,
        FakeAnalyzer: ManifestAnalyzer,
        FakeCorrection: LayerCorrection,
    }
    for registration in original.registry.registrations():
        plugin = replacements.get(
            registration.factory.plugin_type, registration.factory.plugin_type
        )
        bindings = []
        for binding in registration.bindings:
            inputs = binding.inputs
            if require_sign and binding.operation_id == "synthetic:analyze":
                inputs = tuple(
                    replace(port, validator=KnownSignValidator()) for port in inputs
                )
            bindings.append(
                replace(
                    binding,
                    inputs=inputs,
                    handler=replace(
                        binding.handler,
                        plugin_type=plugin,
                        inputs=inputs,
                        wrapper_digest=digest,
                    ),
                )
            )
        registry.register(
            registration.descriptor,
            Factory(plugin, original.config, original.controls),
            tuple(bindings),
        )
    registry.seal()
    return Harness(registry, original.controls, original.config), implementation


def runtime(harness, implementation, workspace):
    return Runtime(
        harness.registry,
        workspace,
        budget=BUDGET,
        implementation_files={
            r.ref: dict(implementation) for r in harness.registry.registrations()
        },
    )
