"""The projector as a remote: power, plus raw JSON-RPC methods via send_command."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import RemoteEntity, RemoteEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BarcoConfigEntry
from .entity import BarcoEntity

PARALLEL_UPDATES = 0

DESCRIPTION = RemoteEntityDescription(key="projector", name=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the remote."""
    async_add_entities([BarcoRemote(entry.runtime_data, DESCRIPTION)])


class BarcoRemote(BarcoEntity, RemoteEntity):
    """Power, and ``send_command`` with method names such as ``system.gotoready``."""

    @property
    def available(self) -> bool:
        """Always, so the projector can be woken."""
        return True

    @property
    def is_on(self) -> bool:
        """Whether the projector is on."""
        return self.coordinator.device.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Power on; wakes the projector first if needed."""
        await self._async_run(self.coordinator.device.async_turn_on())

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power off."""
        await self._async_run(self.coordinator.device.async_turn_off())

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send each command as a parameterless JSON-RPC method."""
        for method in command:
            await self._async_run(self.coordinator.device.async_command(method))
