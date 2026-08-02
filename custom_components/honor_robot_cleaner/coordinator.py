"""DataUpdateCoordinator for Honor Robot Cleaner."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GritApiClient, GritApiError, is_honor_session_error
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, TOKEN_REFRESH_SKEW

_LOGGER = logging.getLogger(__name__)


class HonorRobotCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls cloud status for one robot."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: GritApiClient,
    ) -> None:
        self.client = client
        self.entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        from . import async_persist_client_session, async_start_reauth_once

        try:
            refreshed = await self.client.async_ensure_token(TOKEN_REFRESH_SKEW)
            if refreshed or self.client.credentials_dirty:
                store = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id) or {}
                store["reauth_started"] = False
                async_persist_client_session(self.hass, self.entry, self.client)
            return await self.client.async_get_status()
        except GritApiError as err:
            if is_honor_session_error(err):
                await async_start_reauth_once(self.hass, self.entry, err)
            raise UpdateFailed(str(err)) from err
