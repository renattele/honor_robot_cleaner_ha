"""Honor Robot Cleaner Home Assistant integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .api import GritApiClient
from .const import (
    ATTR_ROOM_IDS,
    ATTR_TIMES,
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
    CONF_WSS_URL,
    DEFAULT_BASE_URL,
    DEFAULT_CALLING_CODE,
    DEFAULT_LANGUAGE,
    DEFAULT_REGION,
    DEFAULT_SUB_TYPE,
    DOMAIN,
    SERVICE_CLEAN_ROOMS,
)
from .coordinator import HonorRobotCoordinator
from .map_parser import parse_map_data, render_map_png
from .wss import GritWssClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.VACUUM,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.CAMERA,
]

CLEAN_ROOMS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ROOM_IDS): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(ATTR_TIMES, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=3)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Register HTTP views and domain services."""
    from homeassistant.helpers.service import async_extract_entity_ids

    from .http_captcha import async_register_captcha_views

    hass.data.setdefault(DOMAIN, {})
    async_register_captcha_views(hass)

    async def async_clean_rooms(call: ServiceCall) -> None:
        room_ids: list[int] = call.data[ATTR_ROOM_IDS]
        times: int = call.data.get(ATTR_TIMES, 1)
        entity_ids = await async_extract_entity_ids(hass, call)
        if not entity_ids:
            _LOGGER.error("clean_rooms: no target vacuum entity")
            return
        registry = er.async_get(hass)
        for entity_id in entity_ids:
            ent = registry.async_get(entity_id)
            if ent is None or ent.platform != DOMAIN:
                _LOGGER.error("Not an Honor vacuum: %s", entity_id)
                continue
            store = hass.data.get(DOMAIN, {}).get(ent.config_entry_id)
            if not store:
                _LOGGER.error("No store for %s", entity_id)
                continue
            client: GritApiClient = store["client"]
            await client.async_clean_rooms(room_ids, times=times)
            await store["coordinator"].async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAN_ROOMS,
        async_clean_rooms,
        schema=CLEAN_ROOMS_SCHEMA,
    )
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
    if client.wss_url:
        data[CONF_WSS_URL] = client.wss_url
    if client.honor_session:
        data[CONF_HONOR_SESSION] = client.honor_session
    return data


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    from .http_captcha import async_register_captcha_views

    async_register_captcha_views(hass)
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
        wss_url=data.get(CONF_WSS_URL, ""),
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

    store: dict = {
        "client": client,
        "coordinator": coordinator,
        "live_map": {},
        "map": {},
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = store

    async def _on_status(status: dict) -> None:
        coordinator.async_set_updated_data(status)

    _last_map_render = {"ts": 0.0}

    async def _on_map(map_data: str) -> None:
        import time

        now = time.time()
        # Live frames arrive ~every 2s; render at most ~every 3s
        if now - _last_map_render["ts"] < 3.0 and store.get("live_map", {}).get("image"):
            store["live_map"]["raw"] = map_data
            return
        parsed = await hass.async_add_executor_job(parse_map_data, map_data)
        if parsed is None:
            return
        image = await hass.async_add_executor_job(render_map_png, parsed)
        live = {
            "raw": map_data,
            "parsed": parsed,
            "image": image,
            "map_id": parsed.map_id,
            "rooms": [
                {"room_id": r.room_id, "name": r.name} for r in parsed.rooms
            ],
        }
        store["live_map"] = live
        store["map"] = {
            "map_id": parsed.map_id,
            "rooms": live["rooms"],
        }
        _last_map_render["ts"] = now
        hass.bus.async_fire(
            f"{DOMAIN}_map_update", {"entry_id": entry.entry_id}
        )

    wss = GritWssClient(
        client,
        on_status=_on_status,
        on_map=_on_map,
        wss_url=client.resolve_wss_url(),
    )
    store["wss"] = wss
    wss.start()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    wss = store.get("wss")
    if wss is not None:
        await wss.async_stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
