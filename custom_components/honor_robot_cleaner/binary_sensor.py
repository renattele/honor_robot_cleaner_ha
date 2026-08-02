"""Binary sensors for Honor Robot Cleaner."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HonorRobotCoordinator
from .entity import device_info_for_entry, robot_is_online


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
        [HonorRobotOnlineBinarySensor(coordinator, device_id, device_info)]
    )


class HonorRobotOnlineBinarySensor(
    CoordinatorEntity[HonorRobotCoordinator], BinarySensorEntity
):
    """Robot cloud online/offline — mirrors Honor AI Space connected flag."""

    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:lan-connect"

    def __init__(
        self,
        coordinator: HonorRobotCoordinator,
        device_id: str,
        device_info: dict,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_online"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool:
        return robot_is_online(self.coordinator.data)
