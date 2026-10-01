"""The projector as a media player: power and input."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import device as d
from .coordinator import BarcoConfigEntry
from .entity import BarcoEntity

PARALLEL_UPDATES = 0

DESCRIPTION = MediaPlayerEntityDescription(key="projector", name=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the player."""
    async_add_entities([BarcoMediaPlayer(entry.runtime_data, DESCRIPTION)])


class BarcoMediaPlayer(BarcoEntity, MediaPlayerEntity):
    """Power and input.

    Always available: an asleep projector is off the network, and turning the
    player on is what wakes it (wake-on-LAN).
    """

    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    @property
    def available(self) -> bool:
        """Always, so the projector can be woken."""
        return True

    @property
    def state(self) -> MediaPlayerState:
        """On while the laser is on or warming up; otherwise off."""
        return MediaPlayerState.ON if self.coordinator.device.is_on else MediaPlayerState.OFF

    @property
    def source_list(self) -> list[str] | None:
        """The projector's inputs."""
        return self.coordinator.data.get(d.SOURCE_LIST)

    @property
    def source(self) -> str | None:
        """The main window's input, while connected."""
        return self.coordinator.data.get(d.INPUT_SOURCE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The projector's own state names."""
        data = self.coordinator.data
        return {
            "system_state": data.get(d.SYSTEM_STATE)
            or ("eco" if self.coordinator.device.sleeping else None),
            "target_state": data.get(d.SYSTEM_TARGETSTATE),
        }

    async def async_turn_on(self) -> None:
        """Power on; wakes the projector from eco mode first if needed."""
        await self._async_run(self.coordinator.device.async_turn_on())

    async def async_turn_off(self) -> None:
        """Power off."""
        await self._async_run(self.coordinator.device.async_turn_off())

    async def async_select_source(self, source: str) -> None:
        """Switch input."""
        await self._async_run(self.coordinator.device.async_select_source(source))
