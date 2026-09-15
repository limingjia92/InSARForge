from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from insarforge.contracts.errors import (
    DuplicatePluginRegistrationError as DuplicatePluginRegistrationError,
)
from insarforge.contracts.errors import (
    OperationBindingError,
    OperationCapabilityUnsatisfiedError,
)
from insarforge.contracts.errors import (
    PluginAPIVersionMismatchError as PluginAPIVersionMismatchError,
)
from insarforge.contracts.errors import PluginRegistryError as PluginRegistryError
from insarforge.contracts.errors import (
    PluginRegistrySealedError as PluginRegistrySealedError,
)
from insarforge.contracts.errors import UnknownPluginError as UnknownPluginError
from insarforge.contracts.identity import PluginDescriptor, PluginKind, PluginRef
from insarforge.contracts.operations import OperationBinding
from insarforge.contracts.values import validate_identifier


@dataclass(frozen=True)
class PluginRegistration:
    descriptor: PluginDescriptor
    factory: Callable[[], object]
    bindings: tuple[OperationBinding, ...]

    def __post_init__(self):
        if type(self.descriptor) is not PluginDescriptor:
            raise TypeError("descriptor")
        if not callable(self.factory):
            raise TypeError("factory")
        bindings = tuple(self.bindings)
        if any(type(binding) is not OperationBinding for binding in bindings):
            raise TypeError("bindings")
        # Declaration order remains enumeration metadata, per ADR0013.
        object.__setattr__(self, "bindings", bindings)

    @property
    def ref(self) -> PluginRef:
        return self.descriptor.ref


class PluginRegistry:
    def __init__(self, required_api_version: int):
        if isinstance(required_api_version, bool) or not isinstance(
            required_api_version, int
        ):
            raise TypeError("required_api_version")
        if required_api_version < 1:
            raise ValueError("required_api_version")
        self._required_api_version = required_api_version
        self._entries: dict[tuple[PluginKind, str], PluginRegistration] = {}
        self._binding_index: dict[
            tuple[PluginKind, str, str, int], OperationBinding
        ] = {}
        self._sealed = False

    @property
    def required_api_version(self):
        return self._required_api_version

    @property
    def is_sealed(self):
        return self._sealed

    def register(
        self,
        descriptor: PluginDescriptor,
        factory: Callable[[], object],
        bindings: tuple[OperationBinding, ...],
    ) -> None:
        if self._sealed:
            raise PluginRegistrySealedError("registry is sealed")
        registration = PluginRegistration(descriptor, factory, bindings)
        if descriptor.api_version != self._required_api_version:
            raise PluginAPIVersionMismatchError("plugin API version mismatch")
        key = (descriptor.kind, descriptor.plugin_id)
        if key in self._entries:
            raise DuplicatePluginRegistrationError("duplicate plugin registration")
        pending: dict[tuple[PluginKind, str, str, int], OperationBinding] = {}
        for binding in registration.bindings:
            binding_key = (*key, binding.operation_id, binding.operation_api_version)
            if binding_key in pending or binding_key in self._binding_index:
                raise OperationBindingError("duplicate operation binding")
            if not set(binding.required_capabilities).issubset(descriptor.capabilities):
                raise OperationCapabilityUnsatisfiedError(
                    "operation binding requires undeclared capability"
                )
            pending[binding_key] = binding
        # All candidate validation precedes publication to either store.
        self._entries[key] = registration
        self._binding_index.update(pending)

    def seal(self) -> None:
        self._sealed = True

    def resolve(self, ref: PluginRef) -> PluginRegistration:
        if not isinstance(ref, PluginRef):
            raise TypeError("ref")
        try:
            registration = self._entries[(ref.kind, ref.plugin_id)]
        except KeyError as exc:
            raise UnknownPluginError("unknown plugin") from exc
        if ref.api_version != registration.descriptor.api_version:
            raise PluginAPIVersionMismatchError("plugin API version mismatch")
        return registration

    def resolve_binding(
        self,
        plugin_ref: PluginRef,
        operation_id: str,
        operation_api_version: int,
    ) -> OperationBinding:
        if type(plugin_ref) is not PluginRef:
            raise TypeError("plugin_ref")
        if type(operation_id) is not str:
            raise TypeError("operation_id")
        validate_identifier(operation_id)
        if type(operation_api_version) is not int:
            raise TypeError("operation_api_version")
        if operation_api_version < 1:
            raise ValueError("operation_api_version")
        registration = self.resolve(plugin_ref)
        key = (
            registration.descriptor.kind,
            registration.descriptor.plugin_id,
            operation_id,
            operation_api_version,
        )
        try:
            return self._binding_index[key]
        except KeyError as exc:
            raise OperationBindingError("unknown operation binding") from exc

    def get_descriptor(self, ref: PluginRef) -> PluginDescriptor:
        return self.resolve(ref).descriptor

    def registrations(
        self, kind: PluginKind | None = None
    ) -> tuple[PluginRegistration, ...]:
        if kind is not None and not isinstance(kind, PluginKind):
            raise TypeError("kind")
        values = (
            self._entries.values()
            if kind is None
            else (r for r in self._entries.values() if r.ref.kind is kind)
        )
        return tuple(
            sorted(
                (r for r in values), key=lambda r: (r.ref.kind.value, r.ref.plugin_id)
            )
        )

    def descriptors(
        self, kind: PluginKind | None = None
    ) -> tuple[PluginDescriptor, ...]:
        return tuple(r.descriptor for r in self.registrations(kind))

    def __len__(self):
        return len(self._entries)
