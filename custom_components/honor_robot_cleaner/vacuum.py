"""Vacuum platform for Honor Robot Cleaner."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GritApiClient, GritApiError
from .const import (
    ATTR_CLEAN_AREA,
    ATTR_CLEAN_TIME,
    ATTR_CONNECTED,
    ATTR_ERROR_INFO,
    ATTR_FAN_STATUS,
    ATTR_FIRMWARE,
    ATTR_LOCAL_IP,
    ATTR_MAP_ID,
    ATTR_ROOMS,
    ATTR_WATER_LEVEL,
    ATTR_WIFI_SSID,
    ATTR_WORKING_STATUS,
    CONF_NAME,
    DOMAIN,
    FAN_SPEEDS,
)
from .coordinator import HonorRobotCoordinator
from .entity import HonorRobotEntity, robot_is_online

_LOGGER = logging.getLogger(__name__)

SUPPORT = (
    VacuumEntityFeature.STATE
    | VacuumEntityFeature.BATTERY
    | VacuumEntityFeature.START
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.FAN_SPEED
    | VacuumEntityFeature.LOCATE
    | VacuumEntityFeature.CLEAN_SPOT
)

CLEANING_STATUSES = {
    "AutoClean",
    "Cleaning",
    "ContinueClean",
    "SelectClean",
    "SpotClean",
    "PlanningRect",
    "Relocation",
    "LocationAlarm",
    "DustCollect",
}
RETURNING_STATUSES = {"BackCharging"}
DOCKED_STATUSES = {
    "PileCharging",
    "DirCharging",
    "ChargeDone",
    "Standby",
    "Hibernating",
    "CleanDone",
    "Reached",
}
PAUSED_STATUSES = {"Pause"}
ERROR_STATUSES = {"Malfunction", "LowPower", "UnReachable"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            HonorRobotVacuum(
                store["coordinator"],
                store["client"],
                entry,
            )
        ]
    )


class HonorRobotVacuum(HonorRobotEntity, StateVacuumEntity):
    """Represent the robot as a vacuum entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = SUPPORT
    _attr_fan_speed_list = FAN_SPEEDS

    def __init__(
        self,
        coordinator: HonorRobotCoordinator,
        client: GritApiClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._entry_id = entry.entry_id
        name = entry.data.get(CONF_NAME) or "Honor Robot Cleaner"
        self._attr_unique_id = f"{entry.data['device_id']}_vacuum"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["device_id"])},
            "name": name,
            "manufacturer": "Honor / Grit",
            "model": entry.data.get("sub_type", "rob-01"),
        }
        self._apply_status(coordinator.data or {})

    @callback
    def _handle_coordinator_update(self) -> None:
        self._apply_status(self.coordinator.data or {})
        self.async_write_ha_state()

    def _apply_status(self, status: dict[str, Any]) -> None:
        online = robot_is_online(status)
        working = status.get("working_status") or "unknown"
        self._attr_battery_level = (
            _as_int(status.get("battery_level")) if online else None
        )
        self._attr_fan_speed = status.get("fan_status") if online else None
        map_info: dict[str, Any] = {}
        if self.hass is not None:
            map_info = (
                self.hass.data.get(DOMAIN, {})
                .get(self._entry_id, {})
                .get("map")
                or {}
            )
        self._attr_extra_state_attributes = {
            ATTR_WORKING_STATUS: "offline" if not online else working,
            ATTR_ERROR_INFO: status.get("error_info"),
            ATTR_LOCAL_IP: status.get("local_ip"),
            ATTR_WIFI_SSID: status.get("wifi_ssid"),
            ATTR_CLEAN_AREA: status.get("clean_area") if online else None,
            ATTR_CLEAN_TIME: status.get("clean_time") if online else None,
            ATTR_FAN_STATUS: status.get("fan_status") if online else None,
            ATTR_WATER_LEVEL: status.get("water_level") if online else None,
            ATTR_FIRMWARE: status.get("vendor_firmware_version"),
            ATTR_CONNECTED: online,
            ATTR_MAP_ID: map_info.get("map_id") or status.get("hismap_id"),
            ATTR_ROOMS: map_info.get("rooms") or [],
        }
        # Keep last activity when going offline — entity itself becomes unavailable.
        self._attr_activity = (
            map_working_status(working) if online else VacuumActivity.IDLE
        )

    async def async_start(self) -> None:
        await self._command(self._client.async_start)

    async def async_pause(self) -> None:
        await self._command(self._client.async_pause)

    async def async_stop(self, **kwargs: Any) -> None:
        await self._command(self._client.async_stop)

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self._command(self._client.async_return_to_base)

    async def async_locate(self, **kwargs: Any) -> None:
        await self._command(self._client.async_locate)

    async def async_clean_spot(self, **kwargs: Any) -> None:
        await self._command(self._client.async_spot)

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        async def _set() -> None:
            await self._client.async_set_fan_status(fan_speed)

        await self._command(_set)

    async def _command(self, func) -> None:
        if not robot_is_online(self.coordinator.data):
            _LOGGER.warning("Robot is offline — command ignored")
            return
        try:
            await func()
        except GritApiError as err:
            _LOGGER.error("Command failed: %s", err)
            raise
        await self.coordinator.async_request_refresh()


def map_working_status(working: str) -> VacuumActivity:
    if working in CLEANING_STATUSES:
        return VacuumActivity.CLEANING
    if working in RETURNING_STATUSES:
        return VacuumActivity.RETURNING
    if working in DOCKED_STATUSES:
        return VacuumActivity.DOCKED
    if working in PAUSED_STATUSES:
        return VacuumActivity.PAUSED
    if working in ERROR_STATUSES or working.startswith("upgrading_"):
        return VacuumActivity.ERROR
    return VacuumActivity.IDLE


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
