"""Shared helpers for Honor robot entity platforms."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

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
