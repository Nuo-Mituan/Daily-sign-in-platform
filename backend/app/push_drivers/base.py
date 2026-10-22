"""Driver primitives shared by built-in and custom push providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class DriverError(ValueError):
    pass


class DriverLoadError(DriverError):
    pass


class DriverValidationError(DriverError):
    pass


class PushDriver(Protocol):
    async def send(
        self, config: dict[str, object], title: str, body: str
    ) -> dict[str, object]: ...


@dataclass
class DriverRecord:
    key: str
    name: str
    version: str
    description: str = ""
    fields: list[dict[str, object]] = field(default_factory=list)
    builtin: bool = False
    active_version: str | None = None
    versions: list[str] = field(default_factory=list)
    enabled: bool = True

    def public(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "fields": self.fields,
            "builtin": self.builtin,
            "active_version": self.active_version or self.version,
            "versions": self.versions,
            "enabled": self.enabled,
        }
