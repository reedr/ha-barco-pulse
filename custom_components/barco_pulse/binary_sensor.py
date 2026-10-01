"""Laser, illumination, input signal and health."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import device as d
from .coordinator import BarcoConfigEntry
from .entity import BarcoValueEntity, BarcoValueMixin

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class BarcoBinaryDescription(BarcoValueMixin, BinarySensorEntityDescription):
    """An on/off projector reading."""


def _health_problem(data: dict) -> bool | None:
    health = data.get(d.SYSTEM_HEALTH)
    return None if health is None else health != "Normal"


BINARY_SENSORS = (
    BarcoBinaryDescription(
        key="laser",
        translation_key="laser",
        value_fn=lambda data: data.get(d.LASER_ON),
    ),
    BarcoBinaryDescription(
        key="illumination",
        translation_key="illumination",
        value_fn=lambda data: data.get(d.ILLUM_ON),
    ),
    BarcoBinaryDescription(
        key="input_active",
        translation_key="input_active",
        value_fn=lambda data: data.get(d.INPUT_ACTIVE),
    ),
    BarcoBinaryDescription(
        key="health_problem",
        translation_key="health_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_health_problem,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BarcoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors."""
    async_add_entities(BarcoBinarySensor(entry.runtime_data, desc) for desc in BINARY_SENSORS)


class BarcoBinarySensor(BarcoValueEntity, BinarySensorEntity):
    """An on/off projector reading."""

    entity_description: BarcoBinaryDescription

    @property
    def is_on(self) -> bool | None:
        """The reading."""
        value = self._value
        return None if value is None else bool(value)
