"""Barco Pulse integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, CONF_MAC, Platform
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import CONF_PIN_CODE
from .coordinator import BarcoCoordinator
from .device import BarcoDevice

_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.REMOTE,
    Platform.SENSOR,
    Platform.MEDIA_PLAYER,
]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Barco device from a config entry."""

    host = entry.options.get(CONF_HOST, entry.data.get(CONF_HOST))
    mac = entry.options.get(CONF_MAC, entry.data.get(CONF_MAC))
    pin_code = entry.options.get(CONF_PIN_CODE, entry.data.get(CONF_PIN_CODE))
    dev = BarcoDevice(
        hass,
        host,
        mac,
        pin_code,
    )
    coord = BarcoCoordinator(hass, entry, dev)
    entry.runtime_data = coord
    await coord.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    if unload_ok:
        await entry.runtime_data.device.async_close()
    return unload_ok
