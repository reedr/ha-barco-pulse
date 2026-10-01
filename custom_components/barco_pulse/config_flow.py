"""Config flow for Barco Pulse."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_MAC

from .const import CONF_LEGACY_ENTRY, CONF_PIN_CODE, DOMAIN, LEGACY_DOMAIN
from .device import (
    SYSTEM_MODEL,
    SYSTEM_NAME,
    BarcoAsleep,
    BarcoAuthError,
    BarcoDevice,
    BarcoError,
    normalize_mac,
)

_LOGGER = logging.getLogger(__name__)

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_MAC): str,
        vol.Optional(CONF_PIN_CODE): str,
    }
)


async def validate(data: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Connect, check the PIN and read the identity; return it or form errors."""
    try:
        device = BarcoDevice(data[CONF_HOST], data[CONF_MAC], data.get(CONF_PIN_CODE))
    except ValueError:
        return None, {CONF_MAC: "invalid_mac"}
    try:
        return await device.async_test_connection(), {}
    except BarcoAsleep:
        return None, {"base": "asleep"}
    except BarcoAuthError:
        return None, {CONF_PIN_CODE: "invalid_auth"}
    except BarcoError as err:
        _LOGGER.warning("Could not connect to %s: %s", data[CONF_HOST], err)
        return None, {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected exception")
        return None, {"base": "unknown"}


def clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Trim fields; store the MAC normalized; drop an empty PIN."""
    data = {k: v.strip() if isinstance(v, str) else v for k, v in user_input.items()}
    if not data.get(CONF_PIN_CODE):
        data.pop(CONF_PIN_CODE, None)
    try:
        data[CONF_MAC] = normalize_mac(data[CONF_MAC])
    except ValueError:
        pass
    return data


class BarcoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Barco Pulse."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._skip_legacy = False

    def _legacy_entries(self) -> list[ConfigEntry]:
        """Entries of the original "Barco" package not yet imported."""
        current = self.hass.config_entries.async_entries(DOMAIN)
        imported = {entry.data.get(CONF_LEGACY_ENTRY) for entry in current}
        return [
            entry
            for entry in self.hass.config_entries.async_entries(LEGACY_DOMAIN)
            if entry.entry_id not in imported
        ]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the projector's address, MAC and PIN."""
        if user_input is None and not self._skip_legacy and self._legacy_entries():
            return self.async_show_menu(step_id="user", menu_options=["import_legacy", "manual"])

        errors: dict[str, str] = {}
        if user_input is not None:
            data = clean(user_input)
            info, errors = await validate(data)
            if info is not None:
                await self.async_set_unique_id(data[CONF_MAC])
                self._abort_if_unique_id_configured(updates={CONF_HOST: data[CONF_HOST]})
                title = info.get(SYSTEM_NAME) or info.get(SYSTEM_MODEL) or "Barco projector"
                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set up a projector instead of importing the old entries."""
        self._skip_legacy = True
        return await self.async_step_user()

    async def async_step_import_legacy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import every old entry: same settings, device and entity IDs."""
        legacies = self._legacy_entries()
        if not legacies:
            return self.async_abort(reason="no_legacy_entry")
        if user_input is None:
            return self.async_show_form(
                step_id="import_legacy",
                description_placeholders={
                    "count": str(len(legacies)),
                    "titles": ", ".join(sorted(entry.title for entry in legacies)),
                },
            )
        first, *rest = legacies
        for legacy in rest:
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_IMPORT},
                    data={CONF_LEGACY_ENTRY: legacy.entry_id},
                )
            )
        return await self._async_create_legacy_entry(first)

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import one old entry (started by import_legacy)."""
        legacy = self.hass.config_entries.async_get_entry(import_data[CONF_LEGACY_ENTRY])
        if legacy is None or legacy.domain != LEGACY_DOMAIN:
            return self.async_abort(reason="no_legacy_entry")
        return await self._async_create_legacy_entry(legacy)

    async def _async_create_legacy_entry(self, legacy: ConfigEntry) -> ConfigFlowResult:
        # The old package kept edits from its options flow in options.
        settings = {**legacy.data, **legacy.options}
        data = clean(
            {
                CONF_HOST: settings.get(CONF_HOST, ""),
                CONF_MAC: settings.get(CONF_MAC, ""),
                CONF_PIN_CODE: str(settings.get(CONF_PIN_CODE) or ""),
            }
        )
        try:
            normalize_mac(data[CONF_MAC])
        except ValueError:
            return self.async_abort(reason="invalid_legacy_entry")
        await self.async_set_unique_id(data[CONF_MAC])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=legacy.title, data={**data, CONF_LEGACY_ENTRY: legacy.entry_id}
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or PIN."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = clean(user_input)
            info, errors = await validate(data)
            if info is not None:
                await self.async_set_unique_id(data[CONF_MAC])
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input or entry.data),
            errors=errors,
        )
