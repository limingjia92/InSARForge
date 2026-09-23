from dataclasses import MISSING, FrozenInstanceError, fields, replace
from typing import get_type_hints

import pytest

from insarforge.contracts.operations import (
    ArtifactDraft,
    InputCodec,
    InputPortContract,
    OutputCodec,
    OutputPortContract,
    OutputRecord,
    PortRecord,
    PortValidator,
    ProductProfileRef,
    RecordSchemaRef,
    ResolvedInput,
)
from insarforge.contracts.values import ArtifactRef
from insarforge.products.validation import ProductValidationReport


class Adapters:
    """Stateless structural fakes; no inheritance from the Protocols."""

    def decode(
        self, artifact: ArtifactRef, payload: bytes, schema: RecordSchemaRef
    ) -> ResolvedInput:
        pytest.fail("decode must not run during static construction")

    def encode(self, value: OutputRecord, schema: RecordSchemaRef) -> ArtifactDraft:
        pytest.fail("encode must not run during static construction")

    def validate(
        self,
        value: PortRecord,
        schema: RecordSchemaRef,
        profile: ProductProfileRef | None,
    ) -> ProductValidationReport:
        pytest.fail("validate must not run during static construction")


def port(direction, **changes):
    adapter = Adapters()
    args = dict(
        port_id="synthetic:port",
        schema=RecordSchemaRef("synthetic:schema", 1),
        profile=None,
        codec=adapter,
        validator=adapter,
    )
    args.update(
        dict(min_count=1, max_count=1) if direction == "input" else dict(count=1)
    )
    args.update(changes)
    value_type = InputPortContract if direction == "input" else OutputPortContract
    return value_type(**args)


@pytest.mark.parametrize(
    "value_type,expected",
    [
        (
            InputPortContract,
            {
                "port_id": str,
                "schema": RecordSchemaRef,
                "profile": ProductProfileRef | None,
                "min_count": int,
                "max_count": int | None,
                "codec": InputCodec,
                "validator": PortValidator,
            },
        ),
        (
            OutputPortContract,
            {
                "port_id": str,
                "schema": RecordSchemaRef,
                "profile": ProductProfileRef | None,
                "count": int,
                "codec": OutputCodec,
                "validator": PortValidator,
            },
        ),
    ],
)
def test_exact_fields_required_arguments_and_annotations(value_type, expected):
    declared = fields(value_type)
    assert tuple(field.name for field in declared) == tuple(expected)
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in declared
    )
    assert get_type_hints(value_type) == expected
    assert value_type.__dataclass_params__.frozen


@pytest.mark.parametrize(
    "minimum,maximum", [(0, 1), (1, 1), (0, None), (1, None), (2, 3), (2, None)]
)
def test_input_cardinality_valid(minimum, maximum):
    value = port("input", min_count=minimum, max_count=maximum)
    assert (value.min_count, value.max_count) == (minimum, maximum)


class IntegerSubclass(int):
    pass


@pytest.mark.parametrize("field", ["min_count", "max_count"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", IntegerSubclass(1)])
def test_input_cardinality_requires_exact_integers(field, value):
    with pytest.raises(TypeError, match=field):
        port("input", **{field: value})


def test_input_minimum_cannot_be_none():
    with pytest.raises(TypeError, match="min_count"):
        port("input", min_count=None)


@pytest.mark.parametrize(
    "minimum,maximum", [(-1, 1), (-1, None), (0, 0), (1, -1), (3, 2)]
)
def test_input_invalid_bounds(minimum, maximum):
    with pytest.raises(ValueError):
        port("input", min_count=minimum, max_count=maximum)


@pytest.mark.parametrize("count", [1, 2, 100])
def test_output_fixed_positive_cardinality(count):
    assert port("output", count=count).count == count


@pytest.mark.parametrize("count", [True, False, 1.0, "1", None, IntegerSubclass(1)])
def test_output_requires_exact_integer(count):
    with pytest.raises(TypeError, match="count"):
        port("output", count=count)


@pytest.mark.parametrize("count", [0, -1])
def test_output_count_cannot_be_optional_or_negative(count):
    with pytest.raises(ValueError, match="count"):
        port("output", count=count)


@pytest.mark.parametrize("direction", ["input", "output"])
@pytest.mark.parametrize(
    "value,error",
    [
        (None, TypeError),
        (1, TypeError),
        ("", ValueError),
        ("bad id", ValueError),
        ("bad\u200b", ValueError),
    ],
)
def test_port_identifier_validation(direction, value, error):
    with pytest.raises(error):
        port(direction, port_id=value)


@pytest.mark.parametrize("direction", ["input", "output"])
def test_ports_retain_exact_references_and_adapter_instances(direction):
    schema = RecordSchemaRef("synthetic:record", 2)
    profile = ProductProfileRef("unrelated:profile", 7)
    codec: InputCodec | OutputCodec = Adapters()
    validator: PortValidator = Adapters()
    value = port(
        direction, schema=schema, profile=profile, codec=codec, validator=validator
    )
    assert value.schema is schema and value.profile is profile
    assert value.codec is codec and value.validator is validator
    assert port(direction, profile=None).profile is None
    for field in fields(value):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field.name, getattr(value, field.name))


class SchemaSubclass(RecordSchemaRef):
    pass


class ProfileSubclass(ProductProfileRef):
    pass


@pytest.mark.parametrize("direction", ["input", "output"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", None),
        ("schema", "synthetic:record"),
        ("schema", {}),
        ("schema", ProductProfileRef("synthetic:profile", 1)),
        ("schema", SchemaSubclass("synthetic:record", 1)),
        ("profile", "synthetic:profile"),
        ("profile", {}),
        ("profile", RecordSchemaRef("synthetic:record", 1)),
        ("profile", ProfileSubclass("synthetic:profile", 1)),
    ],
)
def test_exact_schema_and_profile_types(direction, field, value):
    with pytest.raises(TypeError, match=field):
        port(direction, **{field: value})


@pytest.mark.parametrize("direction", ["input", "output"])
@pytest.mark.parametrize("field", ["codec", "validator"])
@pytest.mark.parametrize(
    "bad",
    [
        None,
        "synthetic:adapter",
        b"payload",
        bytearray(b"payload"),
        object(),
        Adapters,
        lambda: None,
    ],
)
def test_rejects_missing_adapters_ids_classes_and_naked_callbacks(
    direction, field, bad
):
    with pytest.raises(TypeError):
        port(direction, **{field: bad})


@pytest.mark.parametrize(
    "direction,field,method",
    [
        ("input", "codec", "decode"),
        ("output", "codec", "encode"),
        ("input", "validator", "validate"),
        ("output", "validator", "validate"),
    ],
)
def test_wrong_method_shapes_and_descriptors_are_rejected_without_calls(
    direction, field, method
):
    def trap(*args):
        pytest.fail("custom descriptor/property must not execute")

    class Descriptor:
        __get__ = trap
        __call__ = trap

    for invalid in (None, 1, "method", property(trap), Descriptor()):
        adapter = type("InvalidAdapter", (), {method: invalid})()
        with pytest.raises(TypeError):
            port(direction, **{field: adapter})


@pytest.mark.parametrize("direction", ["input", "output"])
def test_no_custom_attribute_lookup_or_adapter_internals_are_evaluated(direction):
    class Guarded(Adapters):
        def __getattribute__(self, name):
            pytest.fail("dynamic attribute access is forbidden")

        def __getattr__(self, name):
            pytest.fail("dynamic attribute fallback is forbidden")

        def __deepcopy__(self, memo):
            pytest.fail("adapter copying is forbidden")

        def __repr__(self):
            pytest.fail("adapter repr is forbidden")

        def __hash__(self):
            pytest.fail("adapter hashing is forbidden")

        def __eq__(self, other):
            pytest.fail("adapter equality is forbidden")

    adapter = Guarded()
    value = port(direction, codec=adapter, validator=adapter)
    assert value.codec is adapter and value.validator is adapter

    class Missing:
        def __getattr__(self, name):
            pytest.fail("missing methods must not trigger dynamic lookup")

    with pytest.raises(TypeError):
        port(direction, codec=Missing())


@pytest.mark.parametrize("decoration", [staticmethod, classmethod])
def test_standard_method_descriptors_can_attach_without_invocation(decoration):
    def never_called(*args):
        pytest.fail("standard descriptor method must not be invoked")

    adapter = type(
        "StaticAdapter",
        (),
        {name: decoration(never_called) for name in ("decode", "encode", "validate")},
    )()
    assert port("input", codec=adapter, validator=adapter).codec is adapter
    assert port("output", codec=adapter, validator=adapter).validator is adapter


def test_individual_ports_do_not_add_binding_collection_rules():
    left = port("input", port_id="synthetic:same")
    right = port("output", port_id="synthetic:same")
    assert left.port_id == right.port_id
    assert replace(left, min_count=0).min_count == 0
