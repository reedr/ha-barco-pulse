"""The JSON-RPC client."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.barco_pulse import device as d
from custom_components.barco_pulse.device import (
    BarcoAsleep,
    BarcoAuthError,
    BarcoDevice,
    normalize_mac,
)

from .conftest import MAC


@pytest.mark.parametrize(
    "text",
    ["00.0d.0a.51.1b.08", "00:0D:0A:51:1B:08", "000d.0a51.1b08", "00-0d-0a-51-1b-08", MAC],
)
def test_normalize_mac(text: str) -> None:
    assert normalize_mac(text) == MAC


@pytest.mark.parametrize("text", ["", "00:0d:0a:51:1b", "zz:0d:0a:51:1b:08", "10.0.1.103"])
def test_bad_mac(text: str) -> None:
    with pytest.raises(ValueError):
        normalize_mac(text)


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0.01)


@pytest.mark.parametrize(("split", "reverse"), [(False, False), (True, False), (False, True)])
async def test_session(barco, split: bool, reverse: bool) -> None:
    barco.split, barco.reverse = split, reverse
    dev = BarcoDevice("127.0.0.1", MAC, "1234")
    seen: list[dict] = []
    dev.set_callback(seen.append)
    try:
        await dev.check_connection()
        await _settle()
        assert dev.online and dev.authenticated
        data = dev.data
        assert data[d.SYSTEM_MODEL] == "Balder CS"
        assert data[d.INLET_T] == 22.6
        assert data[d.OUTPUT_RES] == "5120x2160"
        assert data[d.INPUT_SIGNAL] == "5120x2160@60 Hz"
        assert data[d.SOURCE_LIST][0] == "HDMI"
        assert not dev.is_on

        # One notification carrying several properties updates them all.
        await barco.set_props(
            {
                "environment.temperature.inlet.value": 23.04,
                "environment.temperature.outlet.value": 30.0,
                "system.health": "Warning",
            }
        )
        await _settle()
        assert (dev.data[d.INLET_T], dev.data[d.OUTLET_T]) == (23.0, 30.0)
        assert dev.data[d.SYSTEM_HEALTH] == "Warning"

        await dev.async_turn_on()
        await _settle()
        assert dev.is_on and dev.data[d.LASER_ON]
        await dev.async_select_source("SDI")
        await _settle()
        assert dev.data[d.INPUT_SOURCE] == "SDI"
        assert seen
    finally:
        await dev.async_close()


async def test_bad_pin(barco) -> None:
    dev = BarcoDevice("127.0.0.1", MAC, "9999")
    with pytest.raises(BarcoAuthError):
        await dev.async_test_connection()
    # At runtime a bad PIN still allows monitoring.
    await dev.check_connection()
    assert dev.online and not dev.authenticated
    await dev.async_close()


async def test_asleep(barco) -> None:
    barco.props["system.state"] = "eco"
    dev = BarcoDevice("127.0.0.1", MAC, None)
    with pytest.raises(BarcoAsleep):
        await dev.check_connection()
    assert dev.sleeping and not dev.online
    await dev.async_close()


async def test_goes_to_sleep_and_reconnects(barco) -> None:
    dev = BarcoDevice("127.0.0.1", MAC, None)
    await dev.check_connection()
    await _settle()
    await barco.sleep()
    await _settle()
    assert not dev.online and dev.sleeping
    # Live readings are cleared; identity and source list are kept.
    assert d.INLET_T not in dev.data and dev.data[d.SYSTEM_MODEL] == "Balder CS"
    await barco.wake()
    await dev.async_poll()
    assert dev.online and not dev.sleeping
    await dev.async_close()


async def test_dropped_connection_reconnects(barco) -> None:
    dev = BarcoDevice("127.0.0.1", MAC, None)
    await dev.check_connection()
    await _settle()
    for writer, _ in barco._clients:
        writer.close()
    for _ in range(100):
        await asyncio.sleep(0.02)
        if dev.online and len(barco._clients) == 1:
            break
    assert dev.online
    await dev.async_close()
