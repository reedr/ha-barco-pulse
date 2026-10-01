"""Platform for sensor integration."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BarcoConfigEntry
from .device import (
    DEVICE_INLET_T,
    DEVICE_INPUT_ACTIVE,
    DEVICE_INPUT_SIGNAL,
    DEVICE_LASER_STATUS,
    DEVICE_MAINBOARD_T,
    DEVICE_OUTLET_T,
    DEVICE_OUTPUT_HRES,
    DEVICE_OUTPUT_RES,
    DEVICE_OUTPUT_VRES,
    DEVICE_SYSTEM_STATE,
    DEVICE_SYSTEM_TARGETSTATE,
)
from .entity import BarcoEntity

_LOGGER = logging.getLogger(__name__)

SENSOR_INLET_T = "inlet_temp"
SENSOR_OUTLET_T = "outlet_temp"
SENSOR_MAINBOARD_T = "mainboard_temp"
SENSOR_INPUT_ACTIVE = "input_active"
SENSOR_INPUT_SIGNAL = "input_signal"
SENSOR_OUTPUT_RES = "output_res"
SENSOR_OUTPUT_HRES = "output_hres"
SENSOR_OUTPUT_VRES = "output_vres"
SENSOR_LASER_STATUS = "laser_state"
SENSOR_SYSTEM_STATE = "system_state"
SENSOR_SYSTEM_TARGETSTATE = "system_targetstate"

BARCO_SENSOR_MAP = {
    SENSOR_INLET_T: DEVICE_INLET_T,
    SENSOR_OUTLET_T: DEVICE_OUTLET_T,
    SENSOR_MAINBOARD_T: DEVICE_MAINBOARD_T,
    SENSOR_INPUT_ACTIVE: DEVICE_INPUT_ACTIVE,
    SENSOR_INPUT_SIGNAL: DEVICE_INPUT_SIGNAL,
    SENSOR_LASER_STATUS: DEVICE_LASER_STATUS,
    SENSOR_OUTPUT_VRES: DEVICE_OUTPUT_VRES,
    SENSOR_OUTPUT_HRES: DEVICE_OUTPUT_HRES,
    SENSOR_OUTPUT_RES: DEVICE_OUTPUT_RES,
    SENSOR_SYSTEM_STATE: DEVICE_SYSTEM_STATE,
    SENSOR_SYSTEM_TARGETSTATE: DEVICE_SYSTEM_TARGETSTATE,
}

SENSOR_DESCRIPTIONS = (
    SensorEntityDescription(
        key=SENSOR_INLET_T,
        translation_key=SENSOR_INLET_T,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT
    ),
    SensorEntityDescription(
        key=SENSOR_MAINBOARD_T,
        translation_key=SENSOR_MAINBOARD_T,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT
    ),
    SensorEntityDescription(
        key=SENSOR_INPUT_SIGNAL,
        translation_key=SENSOR_INPUT_SIGNAL,
        device_class=SensorDeviceClass.ENUM,
    ),
    SensorEntityDescription(
        key=SENSOR_OUTLET_T,
        translation_key=SENSOR_OUTLET_T,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT
    ),
    SensorEntityDescription(
        key=SENSOR_OUTPUT_HRES,
        translation_key=SENSOR_OUTPUT_HRES,
        device_class="pixels",
        state_class=SensorStateClass.MEASUREMENT
    ),
    SensorEntityDescription(
        key=SENSOR_OUTPUT_VRES,
        translation_key=SENSOR_OUTPUT_VRES,
        device_class="lines",
        state_class=SensorStateClass.MEASUREMENT
    ),
    SensorEntityDescription(
        key=SENSOR_OUTPUT_RES,
        translation_key=SENSOR_OUTPUT_RES,
        device_class=SensorDeviceClass.ENUM,
    ),
    SensorEntityDescription(
        key=SENSOR_LASER_STATUS,
        translation_key=SENSOR_LASER_STATUS,
        device_class=SensorDeviceClass.ENUM,
    ),
    SensorEntityDescription(
        key=SENSOR_SYSTEM_STATE,
        translation_key=SENSOR_SYSTEM_STATE,
        device_class=SensorDeviceClass.ENUM,
    ),
    SensorEntityDescription(
        key=SENSOR_SYSTEM_TARGETSTATE,
        translation_key=SENSOR_SYSTEM_TARGETSTATE,
        device_class=SensorDeviceClass.ENUM,
    )
)

async def async_setup_entry(hass: HomeAssistant,
                            config_entry: BarcoConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    """Add sensors for passed config_entry in HA."""
    coord = config_entry.runtime_data
    new_entities = [BarcoSensor(coord, desc) for desc in SENSOR_DESCRIPTIONS]
    if new_entities:
        async_add_entities(new_entities)

class BarcoSensor(SensorEntity, BarcoEntity):
    """Sensor class."""

    @property
    def available(self) -> bool:
        """Return online state."""
        dev_sensor = BARCO_SENSOR_MAP[self.entity_description.key]
        return self.coordinator.device.get_sensor_value(dev_sensor) is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""

        dev_sensor = BARCO_SENSOR_MAP[self.entity_description.key]
        self._attr_native_value = self.coordinator.device.get_sensor_value(dev_sensor)
        self.async_write_ha_state()
