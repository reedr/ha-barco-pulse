"""Media player platform for Barco Pulse."""

import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BarcoConfigEntry, BarcoCoordinator
from .entity import BarcoEntity

_LOGGER = logging.getLogger(__name__)

DESC = MediaPlayerEntityDescription(key="projector", translation_key="projector")

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BarcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add Remote entity."""
    coord = config_entry.runtime_data

    async_add_entities([BarcoMediaPlayer(coord)])


class BarcoMediaPlayer(MediaPlayerEntity, BarcoEntity):
    """Projector as media_player."""

    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.TURN_ON
    )
    _attr_media_content_type = MediaType.MOVIE
    _supports_source = True

    def __init__(self, coord: BarcoCoordinator) -> None:
        """Get going."""
        super().__init__(coord, DESC)

    @property
    def available(self) -> bool:
        """Is device online."""
        return self.coordinator.device.online

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self.coordinator.device.is_on

    @property
    def source_list(self) -> list[str]:
        """Source list."""
        return self.coordinator.device.source_list

    @property
    def source(self) -> str:
        """Current source."""
        return self.coordinator.device.source

    async def async_select_source(self, source: str):
        """Change source."""
        await self.coordinator.device.select_source(source)

    async def async_turn_on(self) -> None:
        """Turn the device on."""
        await self.coordinator.device.turn_on()

    async def async_turn_off(self) -> None:
        """Turn the device off."""
        await self.coordinator.device.turn_off()

    @property
    def state(self) -> MediaPlayerState:
        """Current state."""
        return MediaPlayerState.ON if self.is_on else MediaPlayerState.IDLE

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.schedule_update_ha_state()
