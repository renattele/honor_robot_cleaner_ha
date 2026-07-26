"""Switch platform — continue clean, carpet boost, light, DND, zone policy."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GritApiClient
from .const import DOMAIN
from .coordinator import HonorRobotCoordinator
from .entity import device_info_for_entry, status_bool


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    coordinator = store["coordinator"]
    client = store["client"]
    device_id = entry.data["device_id"]
    info = device_info_for_entry(entry)
    async_add_entities(
        [
            HonorBoolSwitch(
                coordinator,
                client,
                device_id,
                info,
                key="continue_clean",
                name="Continue clean",
                icon="mdi:debug-step-over",
                setter=client.async_set_continue_clean,
            ),
            HonorBoolSwitch(
                coordinator,
                client,
                device_id,
                info,
                key="carpet_fan_boost",
                name="Carpet boost",
                icon="mdi:rug",
                setter=client.async_set_carpet_fan_boost,
            ),
            HonorBoolSwitch(
                coordinator,
                client,
                device_id,
                info,
                key="light_on",
                name="Light",
                icon="mdi:led-on",
                setter=client.async_set_light,
            ),
            HonorDndSwitch(coordinator, client, device_id, info),
            HonorBoolSwitch(
                coordinator,
                client,
                device_id,
                info,
                key="zone_policy_enable",
                name="Room custom mode",
                icon="mdi:floor-plan",
                setter=client.async_set_zone_policy,
            ),
        ]
    )


class HonorBoolSwitch(CoordinatorEntity[HonorRobotCoordinator], SwitchEntity):
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
        setter: Callable[[bool], Awaitable[None]],
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._key = key
        self._setter = setter
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool:
        return status_bool(self.coordinator.data or {}, self._key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._setter(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._setter(False)
        await self.coordinator.async_request_refresh()


class HonorDndSwitch(CoordinatorEntity[HonorRobotCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Do not disturb"
    _attr_icon = "mdi:minus-circle"

    def __init__(
        self,
        coordinator: HonorRobotCoordinator,
        client: GritApiClient,
        device_id: str,
        device_info: dict,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{device_id}_undisturb_mode"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool:
        val = (self.coordinator.data or {}).get("undisturb_mode")
        if isinstance(val, str):
            return val.strip().lower() in {"on", "1", "true"}
        return bool(val)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.async_set_undisturb_mode(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.async_set_undisturb_mode(False)
        await self.coordinator.async_request_refresh()
