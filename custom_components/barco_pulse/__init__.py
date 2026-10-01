"""The Barco Pulse integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_MAC, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_PIN_CODE
from .coordinator import BarcoConfigEntry, BarcoCoordinator
from .device import BarcoDevice
from .migration import async_migrate_legacy_entry

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> bool:
    """Set up a projector from a config entry."""
    await async_migrate_legacy_entry(hass, entry)

    device = BarcoDevice(entry.data[CONF_HOST], entry.data[CONF_MAC], entry.data.get(CONF_PIN_CODE))
    # Registered before the coordinator so it runs after the coordinator's shutdown.
    entry.async_on_unload(device.async_close)
    coord = BarcoCoordinator(hass, entry, device)
    entry.runtime_data = coord
    # Never fails: an unreachable projector is just asleep.
    await coord.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
