"""Honor Robot Cleaner Home Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import GritApiClient
from .const import (
    AUTH_MODE_TOKEN,
    CONF_ACCOUNT,
    CONF_AUTH_MODE,
    CONF_BASE_URL,
    CONF_CALLING_CODE,
    CONF_DEVICE_ID,
    CONF_HONOR_SESSION,
    CONF_LANGUAGE,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SUB_TYPE,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_BASE_URL,
    DEFAULT_CALLING_CODE,
    DEFAULT_LANGUAGE,
    DEFAULT_REGION,
    DEFAULT_SUB_TYPE,
    DOMAIN,
)
from .coordinator import HonorRobotCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.VACUUM, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Register HTTP views used by Honor ID captcha during config flow."""
    from .http_captcha import async_register_captcha_views

    hass.data.setdefault(DOMAIN, {})
    async_register_captcha_views(hass)
    return True


def _persist_client_session(entry: ConfigEntry, client: GritApiClient) -> dict:
    data = {
        **entry.data,
        CONF_TOKEN: client.token,
        CONF_REGION: client.region,
        CONF_BASE_URL: client.base_url,
        CONF_TOKEN_EXPIRES_AT: client.token_expires_at,
        CONF_DEVICE_ID: client.device_id or entry.data.get(CONF_DEVICE_ID),
        CONF_AUTH_MODE: client.auth_mode or entry.data.get(CONF_AUTH_MODE),
    }
    if client.honor_session:
        data[CONF_HONOR_SESSION] = client.honor_session
    return data


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    data = {**entry.data, **entry.options}
    client = GritApiClient(
        token=data.get(CONF_TOKEN, ""),
        device_id=data[CONF_DEVICE_ID],
        region=data.get(CONF_REGION, DEFAULT_REGION),
        base_url=data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        sub_type=data.get(CONF_SUB_TYPE, DEFAULT_SUB_TYPE),
        account=data.get(CONF_ACCOUNT, ""),
        password=data.get(CONF_PASSWORD, ""),
        calling_code=data.get(CONF_CALLING_CODE, DEFAULT_CALLING_CODE),
        language=data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
        token_expires_at=data.get(CONF_TOKEN_EXPIRES_AT),
        auth_mode=data.get(CONF_AUTH_MODE, AUTH_MODE_TOKEN),
        honor_session=data.get(CONF_HONOR_SESSION) or {},
    )

    try:
        refreshed = await client.async_ensure_token()
        if refreshed:
            hass.config_entries.async_update_entry(
                entry, data=_persist_client_session(entry, client)
            )
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Initial token refresh skipped/failed; will retry on poll",
            exc_info=True,
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
