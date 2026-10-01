"""Platform for BinarySensor integration."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BarcoConfigEntry
from .device import DEVICE_ILLUM_ON, DEVICE_LASER_ON
from .entity import BarcoEntity

_LOGGER = logging.getLogger(__name__)

SENSOR_LASER_ON = "laser"
SENSOR_ILLUM_ON = "illumination"

SENSOR_MAP = {
    SENSOR_LASER_ON: DEVICE_LASER_ON,
    SENSOR_ILLUM_ON: DEVICE_ILLUM_ON
}

SENSOR_DESCRIPTIONS = (
        BinarySensorEntityDescription(
        key=SENSOR_LASER_ON,
        translation_key=SENSOR_LASER_ON
    ),
    BinarySensorEntityDescription(
        key=SENSOR_ILLUM_ON,
        translation_key=SENSOR_ILLUM_ON
    )
)

async def async_setup_entry(hass: HomeAssistant,
                            config_entry: BarcoConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    """Add BinarySensors for passed config_entry in HA."""
    coord = config_entry.runtime_data
    new_entities = [BarcoBinarySensor(coord, desc) for desc in SENSOR_DESCRIPTIONS]
    if new_entities:
        async_add_entities(new_entities)

class BarcoBinarySensor(BinarySensorEntity, BarcoEntity):
    """BinarySensor class."""

    @property
    def available(self) -> bool:
        """Return online state."""
        dev_sensor = SENSOR_MAP[self.entity_description.key]
        return self.coordinator.device.get_sensor_value(dev_sensor) is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""

        dev_sensor = SENSOR_MAP[self.entity_description.key]
        self._attr_is_on = self.coordinator.device.get_sensor_value(dev_sensor)
        self.async_write_ha_state()
