"""The TV's power state as the TV itself reports it (Active, Screen Off, Active Standby, ...), or unreachable."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CytvConfigEntry
from .entity import CytvEntity

# tvpower/getPowerState's words, as the sensor's options (lower case, as Home Assistant wants them)
STATES = {
    "Active": "active",
    "Screen Off": "screen_off",
    "Screen Saver": "screen_saver",
    "Active Standby": "active_standby",
    "Suspend": "suspend",
    "Power Off": "power_off",
}
OPTIONS = [*STATES.values(), "unknown_state", "unreachable"]


async def async_setup_entry(hass: HomeAssistant, entry: CytvConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([CytvPowerSensor(entry)])


class CytvPowerSensor(CytvEntity, SensorEntity):
    _attr_translation_key = "power_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = OPTIONS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: CytvConfigEntry) -> None:
        super().__init__(entry, "power_state")

    @property
    def native_value(self) -> str:
        if not self._client.connected:
            return "unreachable"
        if not self._client.power_state:
            return "unknown_state"
        return STATES.get(self._client.power_state, "unknown_state")

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"reported": self._client.power_state} if self._client.power_state else {}
