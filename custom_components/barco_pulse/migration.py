"""Registry migration from the original package (domain "Barco")."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_LEGACY_ENTRY, DOMAIN, LEGACY_DOMAIN
from .coordinator import BarcoConfigEntry

_LOGGER = logging.getLogger(__name__)


def legacy_device_id(mac: str) -> str:
    """The old package's device identifier and unique-ID prefix."""
    return f"Barco:{mac}"


async def async_migrate_legacy_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> None:
    """Move the legacy entry's device and entities here, then remove it.

    Registry IDs are kept, so entity IDs, history, names, areas and labels carry
    over. Unique IDs ``Barco:<mac>_<key>`` become ``<mac>_<key>``.
    """
    legacy_id = entry.data.get(CONF_LEGACY_ENTRY)
    if legacy_id is None:
        return

    legacy = hass.config_entries.async_get_entry(legacy_id)
    if legacy is not None and legacy.domain == LEGACY_DOMAIN:
        if legacy.state in (
            ConfigEntryState.LOADED,
            ConfigEntryState.SETUP_RETRY,
            ConfigEntryState.SETUP_IN_PROGRESS,
        ):
            await hass.config_entries.async_unload(legacy_id)

        mac = entry.unique_id
        prefix = f"{legacy_device_id(mac)}_" if mac else None
        ent_reg = er.async_get(hass)
        for entity in er.async_entries_for_config_entry(ent_reg, legacy_id):
            unique_id = entity.unique_id
            if prefix and unique_id.startswith(prefix):
                unique_id = f"{mac}_{unique_id.removeprefix(prefix)}"
            if ent_reg.async_get_entity_id(entity.domain, DOMAIN, unique_id):
                _LOGGER.warning(
                    "%s: %s already exists; leaving it with the old entry",
                    entity.entity_id,
                    unique_id,
                )
                continue
            ent_reg.async_update_entity_platform(
                entity.entity_id,
                DOMAIN,
                new_config_entry_id=entry.entry_id,
                new_unique_id=unique_id,
            )
            _LOGGER.info("Took over %s from the old Barco package", entity.entity_id)

        dev_reg = dr.async_get(hass)
        primary_ident = (LEGACY_DOMAIN, legacy_device_id(mac)) if mac else None
        devices = dr.async_entries_for_config_entry(dev_reg, legacy_id)
        primary = next((d for d in devices if primary_ident in d.identifiers), None)
        if primary is not None:
            # A device of this entry already holding the identifier is an orphan
            # from an interrupted import; the legacy device has the history.
            orphan = dev_reg.async_get_device_by_identifier((DOMAIN, mac), entry.entry_id)
            if (
                orphan is not None
                and orphan.id != primary.id
                and not _has_entities(hass, orphan.id)
            ):
                dev_reg.async_remove_device(orphan.id)
            dev_reg.async_update_device(
                primary.id,
                new_config_entry_id=entry.entry_id,
                new_identifiers={(DOMAIN, mac)},
            )
        for device in devices:
            if device is primary:
                continue
            # Older versions of the package keyed the device by serial number.
            if _has_entities(hass, device.id):
                _LOGGER.warning("Leaving %s with the old entry: it still has entities", device.name)
                continue
            _LOGGER.info("Removing empty old device %s", device.name)
            dev_reg.async_remove_device(device.id)
        await hass.config_entries.async_remove(legacy_id)

    # An interrupted import may also have given an empty old device the identifier.
    _remove_empty_duplicates(hass, entry)
    data = {k: v for k, v in entry.data.items() if k != CONF_LEGACY_ENTRY}
    hass.config_entries.async_update_entry(entry, data=data)


def _has_entities(hass: HomeAssistant, device_id: str) -> bool:
    return bool(
        er.async_entries_for_device(er.async_get(hass), device_id, include_disabled_entities=True)
    )


def _remove_empty_duplicates(hass: HomeAssistant, entry: BarcoConfigEntry) -> None:
    """Keep one device for this entry: the one with entities."""
    dev_reg = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    if len(devices) < 2:
        return
    for device in devices:
        if not _has_entities(hass, device.id):
            _LOGGER.info("Removing empty duplicate device %s", device.name)
            dev_reg.async_remove_device(device.id)
