"""Config and reconfigure flows."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.barco_pulse.const import DOMAIN

from .conftest import DATA, MAC


async def _user(hass: HomeAssistant, data: dict) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(result["flow_id"], data)


async def test_user(hass: HomeAssistant, barco) -> None:
    result = await _user(hass, {**DATA, "mac": "00:0D:0A:51:1B:08 "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Balder CS-2590392444"
    assert result["data"] == DATA
    assert result["result"].unique_id == MAC
    await hass.async_block_till_done()

    result = await _user(hass, DATA)
    assert result["reason"] == "already_configured"


async def test_no_pin(hass: HomeAssistant, barco) -> None:
    result = await _user(hass, {"host": "127.0.0.1", "mac": MAC, "pin_code": ""})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "pin_code" not in result["data"]


@pytest.mark.parametrize(
    ("change", "errors"),
    [
        ({"pin_code": "9999"}, {"pin_code": "invalid_auth"}),
        ({"mac": "not-a-mac"}, {"mac": "invalid_mac"}),
    ],
)
async def test_errors(hass: HomeAssistant, barco, change: dict, errors: dict) -> None:
    result = await _user(hass, {**DATA, **change})
    assert result["errors"] == errors


async def test_cannot_connect(hass: HomeAssistant, barco) -> None:
    await barco.stop()
    result = await _user(hass, DATA)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_asleep(hass: HomeAssistant, barco) -> None:
    barco.props["system.state"] = "eco"
    result = await _user(hass, DATA)
    assert result["errors"] == {"base": "asleep"}


async def test_reconfigure(hass: HomeAssistant, barco) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC, data={**DATA, "pin_code": "1"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == DATA

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**DATA, "mac": "00:0d:0a:00:00:01"}
    )
    assert result["reason"] == "wrong_device"
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
