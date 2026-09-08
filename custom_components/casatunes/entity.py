"""Base zone entity preserving existing registry identifiers."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class CasaTunesDeviceEntity(CoordinatorEntity):
    """A zone on one CasaTunes server."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator, zone, device_id, zone_id):
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone = zone
        self._device_id = device_id

    @property
    def zone_id(self):
        return self._zone_id

    @property
    def zone(self):
        # Retain the last known object while the zone is unavailable.
        return self.coordinator.data.zones_dict.get(self._zone_id, self._zone)

    @property
    def available(self):
        return super().available and self._zone_id in self.coordinator.data.zones_dict

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            manufacturer="CasaTunes",
            name=self.zone.Name,
            sw_version=self.coordinator.data.system.CasaTunesVersion,
        )
