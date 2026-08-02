"""Select platform — water level and active map."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GritApiClient, GritApiError
from .const import DOMAIN, WATER_LEVELS
from .coordinator import HonorRobotCoordinator
from .entity import HonorRobotEntity, device_info_for_entry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    coordinator: HonorRobotCoordinator = store["coordinator"]
    client: GritApiClient = store["client"]
    info = device_info_for_entry(entry)
    device_id = entry.data["device_id"]
    async_add_entities(
        [
            HonorWaterLevelSelect(coordinator, client, device_id, info),
            HonorMapSelect(coordinator, client, device_id, info),
        ]
    )


class HonorWaterLevelSelect(
    HonorRobotEntity, SelectEntity
):
    _attr_has_entity_name = True
    _attr_name = "Water level"
    _attr_icon = "mdi:water"
    _attr_options = list(WATER_LEVELS)

    def __init__(
        self,
        coordinator: HonorRobotCoordinator,
        client: GritApiClient,
        device_id: str,
        device_info: dict,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{device_id}_water_level"
        self._attr_device_info = device_info

    @property
    def current_option(self) -> str | None:
        val = (self.coordinator.data or {}).get("water_level")
        if val in WATER_LEVELS:
            return val
        return None

    async def async_select_option(self, option: str) -> None:
        await self._client.async_set_water_level(option)
        await self.coordinator.async_request_refresh()


class HonorMapSelect(HonorRobotEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Active map"
    _attr_icon = "mdi:map"

    def __init__(
        self,
        coordinator: HonorRobotCoordinator,
        client: GritApiClient,
        device_id: str,
        device_info: dict,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{device_id}_active_map"
        self._attr_device_info = device_info
        self._maps: list[dict[str, Any]] = []
        self._realtime_id: str = ""
        self._options: list[str] = []
        self._labels: dict[str, str] = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_refresh_maps()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Keep current options; map list refreshed on select / manual
        self.async_write_ha_state()

    async def _async_refresh_maps(self) -> None:
        try:
            data = await self._client.async_list_maps()
        except GritApiError as err:
            _LOGGER.warning("Map list failed: %s", err)
            return
        self._maps = list(data.get("map_list") or [])
        self._realtime_id = str(data.get("realtime_map_id") or "")
        # Also surface hismap_id from status when list empty
        status_map = str((self.coordinator.data or {}).get("hismap_id") or "")
        options: list[str] = []
        labels: dict[str, str] = {}
        for m in self._maps:
            mid = str(m.get("map_id") or "")
            if not mid:
                continue
            name = str(m.get("map_name") or f"Map {mid}")
            options.append(mid)
            labels[mid] = name
        if self._realtime_id and self._realtime_id not in options:
            options.insert(0, self._realtime_id)
            labels[self._realtime_id] = f"Realtime ({self._realtime_id})"
        if status_map and status_map not in options:
            options.append(status_map)
            labels[status_map] = f"Map {status_map}"
        self._options = options
        self._labels = labels
        self._attr_options = options or [self._realtime_id or status_map or "none"]
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        if self._realtime_id and self._realtime_id in (self._attr_options or []):
            return self._realtime_id
        status_map = str((self.coordinator.data or {}).get("hismap_id") or "")
        if status_map in (self._attr_options or []):
            return status_map
        opts = self._attr_options or []
        return opts[0] if opts else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "map_names": self._labels,
            "realtime_map_id": self._realtime_id,
        }

    async def async_select_option(self, option: str) -> None:
        if option in {"", "none"}:
            await self._async_refresh_maps()
            return
        name = self._labels.get(option, "")
        await self._client.async_enable_map(option, name)
        await self._async_refresh_maps()
        await self.coordinator.async_request_refresh()
