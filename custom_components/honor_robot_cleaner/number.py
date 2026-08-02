"""Number platform — volume."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GritApiClient
from .const import DOMAIN
from .coordinator import HonorRobotCoordinator
from .entity import HonorRobotEntity, device_info_for_entry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            HonorVolumeNumber(
                store["coordinator"],
                store["client"],
                entry.data["device_id"],
                device_info_for_entry(entry),
            )
        ]
    )


class HonorVolumeNumber(HonorRobotEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_name = "Volume"
    _attr_icon = "mdi:volume-high"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: HonorRobotCoordinator,
        client: GritApiClient,
        device_id: str,
        device_info: dict,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{device_id}_volume"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | None:
        val = (self.coordinator.data or {}).get("volume")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self._client.async_set_volume(int(value))
        await self.coordinator.async_request_refresh()
