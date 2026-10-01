"""Base entity for Barco Pulse."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import BarcoCoordinator
from .device import (
    SYSTEM_FIRMWARE,
    SYSTEM_MODEL,
    SYSTEM_NAME,
    SYSTEM_SERIAL,
    BarcoAsleep,
    BarcoError,
)


class BarcoEntity(CoordinatorEntity[BarcoCoordinator]):
    """An entity of one projector; unique IDs are ``<mac>_<key>``."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BarcoCoordinator, description: EntityDescription) -> None:
        """Set up the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        device = coordinator.device
        data = coordinator.data or {}
        self._attr_unique_id = f"{device.mac}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.mac)},
            connections={(CONNECTION_NETWORK_MAC, format_mac(device.mac))},
            manufacturer=MANUFACTURER,
            model=data.get(SYSTEM_MODEL),
            serial_number=data.get(SYSTEM_SERIAL),
            sw_version=data.get(SYSTEM_FIRMWARE),
            name=data.get(SYSTEM_NAME) or "Barco projector",
            configuration_url=f"http://{device.host}",
        )

    async def _async_run(self, command: Awaitable[None]) -> None:
        """Run a command, reporting failures to the caller."""
        try:
            await command
        except BarcoAsleep as err:
            raise HomeAssistantError("The projector is asleep; turn it on first") from err
        except BarcoError as err:
            raise HomeAssistantError(f"Barco {self.coordinator.device.host}: {err}") from err


@dataclass(frozen=True, kw_only=True)
class BarcoValueMixin:
    """How an entity reads its value from the device data."""

    value_fn: Callable[[dict[str, Any]], Any]


class BarcoValueEntity(BarcoEntity):
    """A reading; unavailable until the projector has reported it."""

    entity_description: BarcoValueMixin  # type: ignore[assignment]

    @property
    def _value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def available(self) -> bool:
        """Available while the projector has a value for this."""
        return super().available and self._value is not None
