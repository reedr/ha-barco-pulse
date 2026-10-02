"""Import of the original package's entry (domain "Barco")."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.barco_pulse.const import DOMAIN, LEGACY_DOMAIN

from .conftest import MAC

OLD_ID = f"Barco:{MAC}"
ENTITIES = {
    ("media_player", "projector"): "barco_000d0a511b08_projector",
    ("remote", "projector"): "barco_000d0a511b08_projector",
    ("sensor", "inlet_temp"): "barco_000d0a511b08_inlet_temp",
    ("sensor", "system_state"): "barco_000d0a511b08_system_state",
    ("binary_sensor", "laser"): "barco_000d0a511b08_laser",
}


async def _wait_available(hass: HomeAssistant, entity_ids: list[str], timeout: float = 5) -> None:
    """Wait for the fake projector's replies to arrive over the socket.

    async_block_till_done() does not wait for socket I/O, so on a slow runner
    the first readings can land just after it returns (CI flake 2026-10-02).
    """
    async with asyncio.timeout(timeout):
        while any(
            (state := hass.states.get(e)) is None or state.state == "unavailable"
            for e in entity_ids
        ):
            await asyncio.sleep(0.05)


def _legacy(hass: HomeAssistant) -> tuple[MockConfigEntry, str]:
    entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Projectors",
        data={"host": "10.9.9.9", "mac": "00.0d.0a.51.1b.08", "pin_code": "0"},
        # The old options flow saved edits here.
        options={"host": "127.0.0.1", "mac": "00.0d.0a.51.1b.08", "pin_code": "1234"},
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(LEGACY_DOMAIN, OLD_ID)}, name=OLD_ID
    )
    ent_reg = er.async_get(hass)
    for (domain, key), object_id in ENTITIES.items():
        ent_reg.async_get_or_create(
            domain,
            LEGACY_DOMAIN,
            f"{OLD_ID}_{key}",
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=object_id,
        )
    ent_reg.async_update_entity(
        "media_player.barco_000d0a511b08_projector", name="Theater Projector"
    )
    # An earlier version keyed the device by serial number; it was left behind, empty.
    stale = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(LEGACY_DOMAIN, "Barco:2590392444")},
        name="Barco:2590392444",
    )
    dr.async_get(hass).async_update_device(stale.id, disabled_by=dr.DeviceEntryDisabler.USER)
    return entry, device.id


async def test_import(hass: HomeAssistant, barco) -> None:
    legacy, device_id = _legacy(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_legacy"}
    )
    assert result["description_placeholders"] == {"count": "1", "titles": "Projectors"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["host"] == "127.0.0.1"
    await hass.async_block_till_done()

    entry = result["result"]
    assert entry.unique_id == MAC
    assert "legacy_entry" not in entry.data
    assert hass.config_entries.async_get_entry(legacy.entry_id) is None

    ent_reg = er.async_get(hass)
    await _wait_available(hass, [f"{d}.{o}" for (d, _), o in ENTITIES.items()])
    for (domain, key), object_id in ENTITIES.items():
        reg = ent_reg.async_get(f"{domain}.{object_id}")
        assert reg.platform == DOMAIN, reg.entity_id
        assert reg.unique_id == f"{MAC}_{key}"
        assert reg.config_entry_id == entry.entry_id
        assert hass.states.get(reg.entity_id).state != "unavailable", reg.entity_id
    player = hass.states.get("media_player.barco_000d0a511b08_projector")
    assert player.attributes["friendly_name"] == "Theater Projector"
    assert player.state == "off"

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    assert device.identifiers == {(DOMAIN, MAC)}
    assert device.model == "Balder CS"
    assert len(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)) == 1
    # The old serial-keyed device is gone.
    assert not [d for d in dev_reg.devices if d.name == "Barco:2590392444"]
    # New readings appear alongside the old ones.
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_health")


async def test_manual(hass: HomeAssistant, barco) -> None:
    _legacy(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    assert result["step_id"] == "user" and result["type"] is FlowResultType.FORM


async def test_resume_interrupted_import(hass: HomeAssistant, barco) -> None:
    """Prod state after the first import attempt failed on the device step."""
    legacy, device_id = _legacy(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        title="Projectors",
        data={"host": "127.0.0.1", "mac": MAC, "pin_code": "1234", "legacy_entry": legacy.entry_id},
    )
    entry.add_to_hass(hass)
    # The entities had been moved, and the empty serial-keyed device had been
    # moved and given the new identifier, before the error.
    for reg in er.async_entries_for_config_entry(ent_reg, legacy.entry_id):
        key = reg.unique_id.removeprefix(f"Barco:{MAC}_")
        ent_reg.async_update_entity_platform(
            reg.entity_id, DOMAIN, new_config_entry_id=entry.entry_id, new_unique_id=f"{MAC}_{key}"
        )
    stale = dev_reg.async_get_device_by_identifier(
        (LEGACY_DOMAIN, "Barco:2590392444"), legacy.entry_id
    )
    dev_reg.async_update_device(
        stale.id, new_config_entry_id=entry.entry_id, new_identifiers={(DOMAIN, MAC)}
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    assert [d.id for d in devices] == [device_id]
    assert dev_reg.async_get(stale.id) is None
    assert hass.config_entries.async_get_entry(legacy.entry_id) is None
    assert "legacy_entry" not in entry.data
    await _wait_available(hass, ["sensor.barco_000d0a511b08_inlet_temp"])
    assert hass.states.get("sensor.barco_000d0a511b08_inlet_temp").state != "unavailable"
