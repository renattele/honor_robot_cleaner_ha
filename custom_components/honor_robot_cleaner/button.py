"""Button platform — spot, continue, locate, clear map."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GritApiClient
from .const import DOMAIN
from .coordinator import HonorRobotCoordinator
from .entity import device_info_for_entry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    coordinator = store["coordinator"]
    client: GritApiClient = store["client"]
    device_id = entry.data["device_id"]
    info = device_info_for_entry(entry)
    async_add_entities(
        [
            HonorActionButton(
                coordinator,
                client,
                device_id,
                info,
                key="spot",
                name="Spot clean",
                icon="mdi:bullseye",
                action=client.async_spot,
            ),
            HonorActionButton(
                coordinator,
                client,
                device_id,
                info,
                key="continue",
                name="Continue cleaning",
                icon="mdi:play",
                action=client.async_continue,
            ),
            HonorActionButton(
                coordinator,
                client,
                device_id,
                info,
                key="locate",
                name="Locate",
                icon="mdi:map-marker",
                action=client.async_locate,
            ),
            HonorActionButton(
                coordinator,
                client,
                device_id,
                info,
                key="clear_map",
                name="Clear map",
                icon="mdi:map-marker-remove",
                action=client.async_clear_map,
            ),
        ]
    )


class HonorActionButton(CoordinatorEntity[HonorRobotCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HonorRobotCoordinator,
        client: GritApiClient,
        device_id: str,
        device_info: dict,
        *,
        key: str,
        name: str,
        icon: str,
        action: Callable[[], Awaitable[None]],
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._action = action
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{device_id}_btn_{key}"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        await self._action()
        await self.coordinator.async_request_refresh()
