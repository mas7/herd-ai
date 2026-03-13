"""Platform registry — maps platform names to adapter instances."""
from __future__ import annotations

from src.platform.contracts import PlatformAdapter


class PlatformRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        self._adapters[adapter.platform_name] = adapter

    def get(self, platform_name: str) -> PlatformAdapter:
        adapter = self._adapters.get(platform_name)
        if adapter is None:
            raise KeyError(
                f"No adapter registered for platform: {platform_name}"
            )
        return adapter

    def all(self) -> list[PlatformAdapter]:
        return list(self._adapters.values())

    @property
    def platform_names(self) -> list[str]:
        return list(self._adapters.keys())
