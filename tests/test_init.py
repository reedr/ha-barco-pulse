"""Setup, entities and control."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.barco_pulse.const import DOMAIN

from .conftest import DATA, MAC

PLAYER = "media_player.balder_cs_2590392444"


async def _setup(hass: HomeAssistant, data: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC, title="Projector", data=data or DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _settle(hass)
    return entry


async def _settle(hass: HomeAssistant) -> None:
    for _ in range(20):
        await asyncio.sleep(0.01)
    await hass.async_block_till_done()


async def _poll(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    await _settle(hass)


async def test_entities(hass: HomeAssistant, barco) -> None:
    entry = await _setup(hass)
    state = hass.states.get(PLAYER)
    assert state.state == "off"
    assert state.attributes["source_list"][:2] == ["HDMI", "DisplayPort 1"]
    assert state.attributes["system_state"] == "ready"

    temp = hass.states.get("sensor.balder_cs_2590392444_inlet_temperature")
    assert float(temp.state) == pytest.approx(22.6)
    assert temp.attributes["unit_of_measurement"] == "°C"
    assert hass.states.get("sensor.balder_cs_2590392444_state").state == "ready"
    assert hass.states.get("sensor.balder_cs_2590392444_health").state == "normal"
    assert hass.states.get("sensor.balder_cs_2590392444_output_resolution").state == "5120x2160"
    assert hass.states.get("binary_sensor.balder_cs_2590392444_hdmi_signal").state == "on"
    assert hass.states.get("binary_sensor.balder_cs_2590392444_laser").state == "off"
    assert hass.states.get("binary_sensor.balder_cs_2590392444_health_problem").state == "off"

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get(PLAYER).unique_id == f"{MAC}_projector"
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), entry.entry_id)
    assert (device.model, device.serial_number, device.sw_version) == (
        "Balder CS",
        "2590392444",
        "2.5.2",
    )
    assert entry.state is ConfigEntryState.LOADED

    await barco.set_props({"system.health": "Error"})
    await _settle(hass)
    assert hass.states.get("binary_sensor.balder_cs_2590392444_health_problem").state == "on"


async def test_control(hass: HomeAssistant, barco) -> None:
    await _setup(hass)
    await hass.services.async_call("media_player", "turn_on", {"entity_id": PLAYER}, blocking=True)
    await _settle(hass)
    assert hass.states.get(PLAYER).state == "on"
    assert hass.states.get(PLAYER).attributes["source"] == "HDMI"
    assert hass.states.get("binary_sensor.balder_cs_2590392444_laser").state == "on"

    await hass.services.async_call(
        "media_player", "select_source", {"entity_id": PLAYER, "source": "SDI"}, blocking=True
    )
    await _settle(hass)
    assert hass.states.get(PLAYER).attributes["source"] == "SDI"

    await hass.services.async_call(
        "remote",
        "send_command",
        {"entity_id": "remote.balder_cs_2590392444", "command": ["system.poweroff"]},
        blocking=True,
    )
    await _settle(hass)
    assert hass.states.get(PLAYER).state == "off"
    assert barco.methods().count("authenticate") == 1


async def test_sleep_and_wake(hass: HomeAssistant, barco, wol) -> None:
    await _setup(hass)
    await barco.sleep()
    await _settle(hass)
    # Readings go unavailable; the player stays usable so it can wake the projector.
    assert hass.states.get("sensor.balder_cs_2590392444_inlet_temperature").state == "unavailable"
    state = hass.states.get(PLAYER)
    assert state.state == "off" and state.attributes["system_state"] == "eco"

    with pytest.raises(HomeAssistantError, match="asleep"):
        await hass.services.async_call(
            "media_player", "select_source", {"entity_id": PLAYER, "source": "SDI"}, blocking=True
        )

    await hass.services.async_call("media_player", "turn_on", {"entity_id": PLAYER}, blocking=True)
    assert wol == ["000d0a511b08"]
    # The wake window's quick retries find it booted, and the pending power-on is sent.
    for _ in range(100):
        await asyncio.sleep(0.02)
        if hass.states.get(PLAYER).state == "on":
            break
    assert hass.states.get(PLAYER).state == "on"
    assert barco.methods().count("system.poweron") == 1


async def test_setup_while_asleep(hass: HomeAssistant, barco) -> None:
    await barco.stop()
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    # Nothing is known yet, so the device has a generic name.
    assert hass.states.get("media_player.barco_projector").state == "off"
    temp = "sensor.barco_projector_inlet_temperature"
    assert hass.states.get(temp).state == "unavailable"
    await barco.wake()
    await _poll(hass)
    assert float(hass.states.get(temp).state) == 22.6
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), entry.entry_id)
    assert device.model == "Balder CS"


async def test_unload(hass: HomeAssistant, barco) -> None:
    entry = await _setup(hass)
    device = entry.runtime_data.device
    assert device.online
    assert await hass.config_entries.async_unload(entry.entry_id)
    await _settle(hass)
    assert not device.online and barco._clients == []


async def test_go_to_ready_wakes(hass: HomeAssistant, barco, wol) -> None:
    """The theater's standby script sends system.gotoready to a sleeping projector."""
    await _setup(hass)
    await barco.sleep()
    await _settle(hass)
    await hass.services.async_call(
        "remote",
        "send_command",
        {"entity_id": "remote.balder_cs_2590392444", "command": ["system.gotoready"]},
        blocking=True,
    )
    assert wol == ["000d0a511b08"]
    for _ in range(100):
        await asyncio.sleep(0.02)
        if "system.gotoready" in barco.methods():
            break
    assert barco.methods().count("system.gotoready") == 1
    assert hass.states.get("sensor.balder_cs_2590392444_state").state == "ready"


async def test_stale_power_on_is_dropped(hass: HomeAssistant, barco) -> None:
    """A power-on queued by a wake that never took isn't sent when the projector turns up later."""
    await _setup(hass)
    await barco.sleep()
    await _settle(hass)
    # This time the wake-on-LAN packet doesn't wake it.
    with patch("custom_components.barco_pulse.device.send_magic_packet") as wol:
        await hass.services.async_call(
            "media_player", "turn_on", {"entity_id": PLAYER}, blocking=True
        )
        assert wol.call_count == 1
    await asyncio.sleep(4.5)  # past BARCO_PENDING_TTL (patched to 4 s)
    await barco.wake()
    await _poll(hass)
    assert entry_online(hass)
    assert "system.poweron" not in barco.methods()
    assert hass.states.get(PLAYER).state == "off"


def entry_online(hass: HomeAssistant) -> bool:
    return hass.config_entries.async_entries(DOMAIN)[0].runtime_data.device.online


async def test_turn_off_while_asleep(hass: HomeAssistant, barco) -> None:
    await _setup(hass)
    await barco.sleep()
    await _settle(hass)
    await hass.services.async_call("media_player", "turn_off", {"entity_id": PLAYER}, blocking=True)
    assert "system.poweroff" not in barco.methods()


async def test_restart_while_asleep_keeps_identity(hass: HomeAssistant, barco) -> None:
    entry = await _setup(hass)
    await barco.stop()
    await hass.config_entries.async_reload(entry.entry_id)
    await _settle(hass)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), entry.entry_id)
    assert (device.name, device.model, device.sw_version) == (
        "Balder CS-2590392444",
        "Balder CS",
        "2.5.2",
    )
    assert hass.states.get(PLAYER).attributes["friendly_name"] == "Balder CS-2590392444"
