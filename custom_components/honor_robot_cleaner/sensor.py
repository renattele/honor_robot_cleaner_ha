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

from .const import DOMAIN
from .coordinator import HonorRobotCoordinator
from .entity import device_info_for_entry, nested_hour, robot_is_online


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HonorRobotCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    device_id = entry.data["device_id"]
    device_info = device_info_for_entry(entry)

    async_add_entities(
        [
            HonorRobotBatterySensor(coordinator, device_id, device_info),
            HonorRobotStatusSensor(coordinator, device_id, device_info),
            HonorRobotCleanAreaSensor(coordinator, device_id, device_info),
            HonorRobotCleanTimeSensor(coordinator, device_id, device_info),
            HonorRobotErrorSensor(coordinator, device_id, device_info),
            HonorRobotFirmwareSensor(coordinator, device_id, device_info),
            HonorRobotTextSensor(
                coordinator,
                device_id,
                device_info,
                key="undisturb_mode",
                name="Do not disturb status",
                icon="mdi:minus-circle-outline",
            ),
            HonorConsumableSensor(
                coordinator,
                device_id,
                device_info,
                group="filter",
                field="used_hour",
                key="filter_used",
                name="Filter used",
            ),
            HonorConsumableSensor(
                coordinator,
                device_id,
                device_info,
                group="filter",
                field="left_hour",
                key="filter_left",
                name="Filter remaining",
            ),
            HonorConsumableSensor(
                coordinator,
                device_id,
                device_info,
                group="rolling_brush",
                field="used_hour",
                key="main_brush_used",
                name="Main brush used",
            ),
            HonorConsumableSensor(
                coordinator,
                device_id,
                device_info,
                group="rolling_brush",
                field="left_hour",
                key="main_brush_left",
                name="Main brush remaining",
            ),
            HonorConsumableSensor(
                coordinator,
                device_id,
                device_info,
                group="side_brush",
                field="used_hour",
                key="side_brush_used",
                name="Side brush used",
            ),
            HonorConsumableSensor(
                coordinator,
                device_id,
                device_info,
                group="side_brush",
                field="left_hour",
                key="side_brush_left",
                name="Side brush remaining",
            ),
        ]
    )


class HonorRobotBaseSensor(CoordinatorEntity[HonorRobotCoordinator], SensorEntity):
    _attr_has_entity_name = True
    # Most status sensors stay readable while offline; controls go unavailable.
    _available_when_offline = True

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

    @property
    def available(self) -> bool:
        if self._available_when_offline:
            return super().available
        return super().available and robot_is_online(self.coordinator.data)


class HonorRobotBatterySensor(HonorRobotBaseSensor):
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device_id, device_info) -> None:
        super().__init__(coordinator, device_id, device_info, "battery")

    @property
    def native_value(self):
        if not robot_is_online(self.coordinator.data):
            return None
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
        if not robot_is_online(self.coordinator.data):
            return "offline"
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


class HonorRobotErrorSensor(HonorRobotBaseSensor):
    _attr_name = "Error"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, device_id, device_info) -> None:
        super().__init__(coordinator, device_id, device_info, "error_info")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("error_info") or "none"


class HonorRobotFirmwareSensor(HonorRobotBaseSensor):
    _attr_name = "Firmware"
    _attr_icon = "mdi:chip"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, device_id, device_info) -> None:
        super().__init__(coordinator, device_id, device_info, "firmware")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("vendor_firmware_version")


class HonorRobotTextSensor(HonorRobotBaseSensor):
    def __init__(
        self,
        coordinator,
        device_id,
        device_info,
        *,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, device_id, device_info, key)
        self._attr_name = name
        self._attr_icon = icon

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._key)


class HonorConsumableSensor(HonorRobotBaseSensor):
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:wrench-clock"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator,
        device_id,
        device_info,
        *,
        group: str,
        field: str,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator, device_id, device_info, key)
        self._group = group
        self._field = field
        self._attr_name = name

    @property
    def native_value(self):
        return nested_hour(self.coordinator.data or {}, self._group, self._field)
