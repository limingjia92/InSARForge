"""Versioned, immutable runtime evidence; no executor or locator access."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from insarforge.contracts._execution_json import canonical, fields, plain
from insarforge.contracts.errors import ContractError
from insarforge.contracts.execution import _artifact_dict, _artifact_from_dict
from insarforge.contracts.fingerprints import is_digest
from insarforge.contracts.values import ArtifactRef, freeze_json
from insarforge.products.semantics import SemanticStatus, SemanticValue


@dataclass(frozen=True)
class PreparationEvidence:
    semantic_execution_identity: SemanticValue
    preparation: object

    def __post_init__(self):
        value = self.semantic_execution_identity
        if type(value) is not SemanticValue or value.status not in (
            SemanticStatus.KNOWN,
            SemanticStatus.UNKNOWN,
        ):
            raise ContractError("PREPARATION_IDENTITY")
        if value.status is SemanticStatus.KNOWN and not isinstance(
            value.value, Mapping
        ):
            raise ContractError("PREPARATION_IDENTITY_SHAPE")
        if not isinstance(self.preparation, Mapping):
            raise ContractError("PREPARATION_OBJECT")
        object.__setattr__(self, "preparation", freeze_json(self.preparation))
        canonical(self.to_dict())

    def to_dict(self):
        value = self.semantic_execution_identity
        return dict(
            schema_version=1,
            status=value.status.value,
            value=plain(value.value),
            reason_code=value.reason_code,
            evidence_refs=[_artifact_dict(r) for r in value.evidence_refs],
            preparation=plain(self.preparation),
        )

    @classmethod
    def from_dict(cls, data):
        fields(
            data, "schema_version status value reason_code evidence_refs preparation"
        )
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ContractError("PREPARATION_VERSION")
        if type(data["evidence_refs"]) is not list:
            raise ContractError("PREPARATION_REFS")
        return cls(
            SemanticValue(
                SemanticStatus(data["status"]),
                freeze_json(data["value"]),
                data["reason_code"],
                tuple(_artifact_from_dict(r) for r in data["evidence_refs"]),
            ),
            data["preparation"],
        )


@dataclass(frozen=True)
class ArtifactEvidence:
    """Complete recipe-aware recomputation material, never a verified flag.

    The exact manifest-bound ref, producing recipe, output port and ordered
    producing inputs are explicit. Runtime recomputes actual content/assets
    against this material before granting an effective strong identity.
    """

    artifact: ArtifactRef
    producer_fingerprint: str
    output_port: str
    ordered_inputs: object

    def __post_init__(self):
        if type(self.artifact) is not ArtifactRef or not is_digest(
            self.producer_fingerprint
        ):
            raise ContractError("ARTIFACT_EVIDENCE_IDENTITY")
        if type(self.output_port) is not str or not self.output_port:
            raise ContractError("ARTIFACT_EVIDENCE_PORT")
        if not isinstance(self.ordered_inputs, Mapping):
            raise ContractError("ARTIFACT_EVIDENCE_INPUTS")
        owned = {}
        for port, refs in self.ordered_inputs.items():
            if type(port) is not str or not port or type(refs) not in (tuple, list):
                raise ContractError("ARTIFACT_EVIDENCE_INPUTS")
            if any(type(ref) is not ArtifactRef for ref in refs):
                raise ContractError("ARTIFACT_EVIDENCE_INPUTS")
            owned[port] = tuple(refs)
        object.__setattr__(self, "ordered_inputs", MappingProxyType(owned))
        canonical(self.to_dict())

    def to_dict(self):
        return dict(
            schema_version=1,
            artifact=_artifact_dict(self.artifact),
            producer_fingerprint=self.producer_fingerprint,
            output_port=self.output_port,
            ordered_inputs={
                p: [_artifact_dict(r) for r in refs]
                for p, refs in self.ordered_inputs.items()
            },
        )

    @classmethod
    def from_dict(cls, data):
        fields(
            data,
            "schema_version artifact producer_fingerprint output_port ordered_inputs",
        )
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ContractError("ARTIFACT_EVIDENCE_VERSION")
        if type(data["ordered_inputs"]) is not dict or any(
            type(v) is not list for v in data["ordered_inputs"].values()
        ):
            raise ContractError("ARTIFACT_EVIDENCE_INPUTS")
        return cls(
            _artifact_from_dict(data["artifact"]),
            data["producer_fingerprint"],
            data["output_port"],
            {
                p: tuple(_artifact_from_dict(r) for r in refs)
                for p, refs in data["ordered_inputs"].items()
            },
        )
