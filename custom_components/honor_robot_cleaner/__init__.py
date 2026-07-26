"""Honor Robot Cleaner Home Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import GritApiClient
from .const import (
    CONF_BASE_URL,
    CONF_DEVICE_ID,
    CONF_REGION,
    CONF_SUB_TYPE,
    CONF_TOKEN,
    DEFAULT_BASE_URL,
    DEFAULT_REGION,
    DEFAULT_SUB_TYPE,
    DOMAIN,
)
from .coordinator import HonorRobotCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.VACUUM, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    data = {**entry.data, **entry.options}
    client = GritApiClient(
        token=data[CONF_TOKEN],
        device_id=data[CONF_DEVICE_ID],
        region=data.get(CONF_REGION, DEFAULT_REGION),
        base_url=data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        sub_type=data.get(CONF_SUB_TYPE, DEFAULT_SUB_TYPE),
    )
    coordinator = HonorRobotCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
