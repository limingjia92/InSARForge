from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from insarforge.contracts.identity import PluginDescriptor, PluginKind, PluginRef


class PluginRegistryError(RuntimeError):
    pass


class DuplicatePluginRegistrationError(PluginRegistryError):
    pass


class UnknownPluginError(PluginRegistryError):
    pass


class PluginRegistrySealedError(PluginRegistryError):
    pass


class PluginAPIVersionMismatchError(PluginRegistryError):
    pass


@dataclass(frozen=True)
class PluginRegistration:
    descriptor: PluginDescriptor
    factory: Callable[[], object]

    def __post_init__(self):
        if not isinstance(self.descriptor, PluginDescriptor):
            raise TypeError("descriptor")
        if not callable(self.factory):
            raise TypeError("factory")

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
        self._entries = {}
        self._sealed = False

    @property
    def required_api_version(self):
        return self._required_api_version

    @property
    def is_sealed(self):
        return self._sealed

    def register(
        self, descriptor: PluginDescriptor, factory: Callable[[], object]
    ) -> None:
        if self._sealed:
            raise PluginRegistrySealedError("registry is sealed")
        if not isinstance(descriptor, PluginDescriptor):
            raise TypeError("descriptor")
        if not callable(factory):
            raise TypeError("factory")
        if descriptor.api_version != self._required_api_version:
            raise PluginAPIVersionMismatchError("plugin API version mismatch")
        key = (descriptor.ref.kind, descriptor.ref.plugin_id)
        if key in self._entries:
            raise DuplicatePluginRegistrationError("duplicate plugin registration")
        self._entries[key] = PluginRegistration(descriptor, factory)

    def seal(self) -> None:
        self._sealed = True

    def resolve(self, ref: PluginRef) -> PluginRegistration:
        if not isinstance(ref, PluginRef):
            raise TypeError("ref")
        try:
            return self._entries[(ref.kind, ref.plugin_id)]
        except KeyError as exc:
            raise UnknownPluginError("unknown plugin") from exc

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
