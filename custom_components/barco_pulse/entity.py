"""Barco Entity Base class."""

import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import BarcoCoordinator
from .device import DEVICE_MODEL, BarcoDevice

_LOGGER = logging.getLogger(__name__)


class BarcoEntity(CoordinatorEntity[BarcoCoordinator]):
    """Base class."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BarcoCoordinator, desc: EntityDescription) -> None:
        """Set up entity."""
        super().__init__(coordinator, desc)

        self.entity_description = desc
        self._state = None
        self._attr_name = desc.key
        self._attr_unique_id = f"{self.coordinator.device.device_id}_{self.device_id}"
        _LOGGER.debug("%s", self.unique_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device.device_id)},
            manufacturer=MANUFACTURER,
            name=coordinator.device.device_id,
        )
#        _LOGGER.error(f"new entity={entity} name={self._attr_name} unique_id={self.unique_id}")

    @property
    def entity_type(self) -> str | None:
        """Type of entity."""
        return None

    @property
    def device_id(self):
        """Return entity id."""
        return self.entity_description.key

    @property
    def device(self) -> BarcoDevice:
        """Return device."""
        return self.coordinator.device

    @property
    def state(self):
        """Return state."""
        return self._state
