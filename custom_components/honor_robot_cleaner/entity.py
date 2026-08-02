"""Shared helpers for Honor robot entity platforms."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DOMAIN
from .coordinator import HonorRobotCoordinator


def device_info_for_entry(entry: ConfigEntry) -> dict[str, Any]:
    device_id = entry.data["device_id"]
    name = entry.data.get(CONF_NAME) or "Honor Robot Cleaner"
    return {
        "identifiers": {(DOMAIN, device_id)},
        "name": name,
        "manufacturer": "Honor / Grit",
        "model": entry.data.get("sub_type", "rob-01"),
    }


def robot_is_online(status: dict[str, Any] | None) -> bool:
    """Match Honor APK: online iff thing_status.connected equals \"true\"."""
    if not status:
        return False
    val = status.get("connected")
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() == "true"
    if isinstance(val, (int, float)):
        return val == 1
    return False


def status_bool(status: dict[str, Any], key: str) -> bool:
    val = status.get(key)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "on", "yes"}
    return bool(val)


def nested_hour(status: dict[str, Any], group: str, field: str) -> int | None:
    raw = status.get(group)
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw.get(field))
    except (TypeError, ValueError):
        return None


def normalize_thing_status(status: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with connected normalized to bool."""
    out = dict(status)
    out["connected"] = robot_is_online(out)
    return out


class HonorRobotEntity(CoordinatorEntity[HonorRobotCoordinator]):
    """Entity unavailable while the robot reports offline."""

    @property
    def available(self) -> bool:
        return super().available and robot_is_online(self.coordinator.data)
