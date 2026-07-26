"""Map camera — PNG snapshot from reuse_map_get."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GritApiClient, GritApiError
from .const import ATTR_MAP_ID, ATTR_ROOMS, DOMAIN
from .coordinator import HonorRobotCoordinator
from .entity import device_info_for_entry
from .map_parser import ParsedMap, parse_map_data, render_map_png

_LOGGER = logging.getLogger(__name__)

# Avoid hammering cloud on every camera card refresh
_MIN_REFRESH_SECONDS = 60


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            HonorMapCamera(
                store["coordinator"],
                store["client"],
                entry,
                store,
            )
        ]
    )


class HonorMapCamera(CoordinatorEntity[HonorRobotCoordinator], Camera):
    _attr_has_entity_name = True
    _attr_name = "Map"
    _attr_icon = "mdi:map-outline"

    def __init__(
        self,
        coordinator: HonorRobotCoordinator,
        client: GritApiClient,
        entry: ConfigEntry,
        store: dict[str, Any],
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._client = client
        self._store = store
        device_id = entry.data["device_id"]
        self._attr_unique_id = f"{device_id}_map"
        self._attr_device_info = device_info_for_entry(entry)
        self._image: bytes | None = None
        self._parsed: ParsedMap | None = None
        self._map_id: str = ""
        self._last_fetch: float = 0.0
        self._content_type = "image/png"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_refresh_map(force=True)

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        await self._async_refresh_map(force=False)
        return self._image

    async def _async_refresh_map(self, *, force: bool) -> None:
        now = datetime.now(timezone.utc).timestamp()
        if (
            not force
            and self._image is not None
            and (now - self._last_fetch) < _MIN_REFRESH_SECONDS
        ):
            return

        map_id = await self._resolve_map_id()
        raw_map: dict[str, Any] = {}
        if map_id:
            try:
                raw_map = await self._client.async_get_map(map_id)
            except GritApiError as err:
                _LOGGER.warning("reuse_map_get failed: %s", err)

        map_data = raw_map.get("map_data") if raw_map else None
        parsed = parse_map_data(map_data, map_id=map_id) if map_data else None
        if parsed is None:
            parsed = ParsedMap(map_id=map_id)

        # Room list may also live on list payload
        if not parsed.rooms and raw_map:
            alt = parse_map_data(raw_map, map_id=map_id)
            if alt and alt.rooms:
                parsed.rooms = alt.rooms

        self._parsed = parsed
        self._map_id = map_id
        self._image = await self.hass.async_add_executor_job(render_map_png, parsed)
        self._last_fetch = now
        self._store["map"] = {
            "map_id": map_id,
            "rooms": [
                {"room_id": r.room_id, "name": r.name} for r in parsed.rooms
            ],
        }
        self.async_write_ha_state()

    async def _resolve_map_id(self) -> str:
        status = self.coordinator.data or {}
        candidates = [
            str(status.get("hismap_id") or ""),
            str(status.get("realtime_map_id") or ""),
        ]
        try:
            data = await self._client.async_list_maps()
            rt = str(data.get("realtime_map_id") or "")
            if rt:
                candidates.insert(0, rt)
            for m in data.get("map_list") or []:
                mid = str(m.get("map_id") or "")
                if mid:
                    candidates.append(mid)
        except GritApiError as err:
            _LOGGER.debug("Map list for camera: %s", err)

        for mid in candidates:
            if mid and mid not in {"0", "none", "None"}:
                return mid
        return ""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rooms = []
        if self._parsed:
            rooms = [
                {"room_id": r.room_id, "name": r.name} for r in self._parsed.rooms
            ]
        return {
            ATTR_MAP_ID: self._map_id or None,
            ATTR_ROOMS: rooms,
        }
