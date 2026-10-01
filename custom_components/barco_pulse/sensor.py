"""Temperatures, signal, resolution and state."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import device as d
from .coordinator import BarcoConfigEntry
from .entity import BarcoValueEntity, BarcoValueMixin

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class BarcoSensorDescription(BarcoValueMixin, SensorEntityDescription):
    """A projector reading."""


def _temperature(key: str, data_key: str) -> BarcoSensorDescription:
    return BarcoSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get(data_key),
    )


SENSORS = (
    _temperature("inlet_temp", d.INLET_T),
    _temperature("outlet_temp", d.OUTLET_T),
    _temperature("mainboard_temp", d.MAINBOARD_T),
    BarcoSensorDescription(
        key="input_signal",
        translation_key="input_signal",
        value_fn=lambda data: data.get(d.INPUT_SIGNAL),
    ),
    BarcoSensorDescription(
        key="output_res",
        translation_key="output_res",
        value_fn=lambda data: data.get(d.OUTPUT_RES),
    ),
    BarcoSensorDescription(
        key="output_hres",
        translation_key="output_hres",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get(d.OUTPUT_HRES),
    ),
    BarcoSensorDescription(
        key="output_vres",
        translation_key="output_vres",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get(d.OUTPUT_VRES),
    ),
    BarcoSensorDescription(
        key="laser_state",
        translation_key="laser_state",
        value_fn=lambda data: data.get(d.LASER_STATUS),
    ),
    BarcoSensorDescription(
        key="system_state",
        translation_key="system_state",
        device_class=SensorDeviceClass.ENUM,
        options=d.STATES,
        value_fn=lambda data: data.get(d.SYSTEM_STATE),
    ),
    BarcoSensorDescription(
        key="system_targetstate",
        translation_key="system_targetstate",
        device_class=SensorDeviceClass.ENUM,
        options=d.STATES,
        value_fn=lambda data: data.get(d.SYSTEM_TARGETSTATE),
    ),
    BarcoSensorDescription(
        key="health",
        translation_key="health",
        device_class=SensorDeviceClass.ENUM,
        options=[s.lower() for s in d.HEALTH_STATES],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (data.get(d.SYSTEM_HEALTH) or "").lower() or None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors."""
    async_add_entities(BarcoSensor(entry.runtime_data, desc) for desc in SENSORS)


class BarcoSensor(BarcoValueEntity, SensorEntity):
    """A projector reading."""

    entity_description: BarcoSensorDescription

    @property
    def native_value(self):
        """The reading; enum values outside the known set are reported as unknown."""
        value = self._value
        options = self.entity_description.options
        if options is not None and value not in options:
            return None
        return value
