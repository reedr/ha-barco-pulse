"""Fixtures for Barco Pulse tests."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from .fake_barco import FakeBarco

pytest_plugins = ("pytest_homeassistant_custom_component",)

MAC = "000d0a511b08"
DATA = {"host": "127.0.0.1", "mac": MAC, "pin_code": "1234"}


@pytest.fixture(autouse=True)
def enable_integration(enable_custom_integrations):
    """Allow Home Assistant to load the custom integration under test."""


@pytest.fixture(autouse=True)
def fast_timing():
    """Shrink the client's delays."""
    module = "custom_components.barco_pulse.const"
    with (
        patch(f"{module}.BARCO_CONNECT_TIMEOUT", 0.5),
        patch(f"{module}.BARCO_LOGIN_TIMEOUT", 0.5),
        patch(f"{module}.BARCO_RECONNECT_DELAY", 0.05),
        patch(f"{module}.BARCO_RECONNECT_DELAY_MAX", 0.1),
        patch(f"{module}.BARCO_WAKE_WINDOW", 3),
        patch(f"{module}.BARCO_PENDING_TTL", 4),
    ):
        yield


@pytest.fixture
async def barco(socket_enabled):
    """A fake projector; the integration reaches it at 127.0.0.1."""
    server = FakeBarco()
    await server.start()
    with patch("custom_components.barco_pulse.const.BARCO_PORT", server.port):
        yield server
    await server.stop()


@pytest.fixture
async def wol(barco):
    """Wake-on-LAN packets wake the fake projector (if it is asleep)."""
    loop = asyncio.get_running_loop()
    sent: list[str] = []

    def send(mac: str) -> None:
        sent.append(mac)
        loop.call_soon_threadsafe(lambda: loop.create_task(_wake()))

    async def _wake() -> None:
        if barco._server is None:
            await barco.wake()

    with patch("custom_components.barco_pulse.device.send_magic_packet", send):
        yield sent
