"""Sensor platform for Honor Robot Cleaner."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DOMAIN
from .coordinator import HonorRobotCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HonorRobotCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_id = entry.data["device_id"]
    name = entry.data.get(CONF_NAME) or "Honor Robot Cleaner"
    device_info = {
        "identifiers": {(DOMAIN, device_id)},
        "name": name,
        "manufacturer": "Honor / Grit",
        "model": entry.data.get("sub_type", "rob-01"),
    }

    async_add_entities(
        [
            HonorRobotBatterySensor(coordinator, device_id, device_info),
            HonorRobotStatusSensor(coordinator, device_id, device_info),
            HonorRobotCleanAreaSensor(coordinator, device_id, device_info),
            HonorRobotCleanTimeSensor(coordinator, device_id, device_info),
        ]
    )


class HonorRobotBaseSensor(CoordinatorEntity[HonorRobotCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HonorRobotCoordinator,
        device_id: str,
        device_info: dict,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = device_info


class HonorRobotBatterySensor(HonorRobotBaseSensor):
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device_id, device_info) -> None:
        super().__init__(coordinator, device_id, device_info, "battery")

    @property
    def native_value(self):
        value = (self.coordinator.data or {}).get("battery_level")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None


class HonorRobotStatusSensor(HonorRobotBaseSensor):
    _attr_name = "Working status"
    _attr_icon = "mdi:robot-vacuum"

    def __init__(self, coordinator, device_id, device_info) -> None:
        super().__init__(coordinator, device_id, device_info, "working_status")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("working_status")


class HonorRobotCleanAreaSensor(HonorRobotBaseSensor):
    _attr_name = "Clean area"
    _attr_native_unit_of_measurement = UnitOfArea.SQUARE_METERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:texture-box"

    def __init__(self, coordinator, device_id, device_info) -> None:
        super().__init__(coordinator, device_id, device_info, "clean_area")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("clean_area")


class HonorRobotCleanTimeSensor(HonorRobotBaseSensor):
    _attr_name = "Clean time"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, device_id, device_info) -> None:
        super().__init__(coordinator, device_id, device_info, "clean_time")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("clean_time")
