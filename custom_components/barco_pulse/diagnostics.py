"""Diagnostics for Barco Pulse."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_PIN_CODE
from .coordinator import BarcoConfigEntry

TO_REDACT = {CONF_PIN_CODE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BarcoConfigEntry
) -> dict[str, Any]:
    """Return the entry (PIN redacted) and the projector's last values."""
    coord = entry.runtime_data
    device = coord.device
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "online": device.online,
        "sleeping": device.sleeping,
        "authenticated": device.authenticated,
        "data": device.data,
    }
