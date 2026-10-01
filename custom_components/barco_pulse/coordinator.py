"""Coordinator for a Barco Pulse projector."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, UPDATE_INTERVAL
from .device import (
    SYSTEM_FIRMWARE,
    SYSTEM_MODEL,
    SYSTEM_SERIAL,
    BarcoDevice,
    BarcoError,
)

_LOGGER = logging.getLogger(__name__)

type BarcoConfigEntry = ConfigEntry[BarcoCoordinator]


class BarcoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Relays the projector's pushed changes; polls to reconnect and to notice wake-ups.

    An unreachable projector is normally just asleep (eco mode takes it off the
    network), so a failed poll isn't an error: the readings clear and go
    unavailable, while the player stays available so it can wake the projector.
    """

    config_entry: BarcoConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: BarcoConfigEntry, device: BarcoDevice
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"Barco {device.host}",
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.device = device
        self._identity: tuple | None = None
        device.set_callback(self._handle_push)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self.device.async_poll()
        except (BarcoError, OSError, TimeoutError) as err:
            _LOGGER.debug("Poll of %s: %s", self.device.host, err)
        return self.device.data

    @callback
    def _handle_push(self, data: dict[str, Any]) -> None:
        self.async_set_updated_data(data)
        self._update_device_registry(data)

    @callback
    def _update_device_registry(self, data: dict[str, Any]) -> None:
        """Fill in model, serial and firmware once the projector has reported them."""
        identity = (data.get(SYSTEM_MODEL), data.get(SYSTEM_SERIAL), data.get(SYSTEM_FIRMWARE))
        if identity == self._identity or not any(identity):
            return
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device_by_identifier(
            (DOMAIN, self.device.mac), self.config_entry.entry_id
        )
        if device is None:
            return
        self._identity = identity
        model, serial, firmware = identity
        dev_reg.async_update_device(
            device.id,
            model=model or device.model,
            serial_number=serial or device.serial_number,
            sw_version=firmware or device.sw_version,
        )
