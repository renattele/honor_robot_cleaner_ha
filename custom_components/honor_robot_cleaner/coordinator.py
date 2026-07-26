"""DataUpdateCoordinator for Honor Robot Cleaner."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GritApiClient, GritApiError
from .const import (
    CONF_AUTH_MODE,
    CONF_BASE_URL,
    CONF_HONOR_SESSION,
    CONF_REGION,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    TOKEN_REFRESH_SKEW,
)

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
        try:
            refreshed = await self.client.async_ensure_token(TOKEN_REFRESH_SKEW)
            if refreshed:
                data = {
                    **self.entry.data,
                    CONF_TOKEN: self.client.token,
                    CONF_REGION: self.client.region,
                    CONF_BASE_URL: self.client.base_url,
                    CONF_TOKEN_EXPIRES_AT: self.client.token_expires_at,
                    CONF_AUTH_MODE: self.client.auth_mode
                    or self.entry.data.get(CONF_AUTH_MODE),
                }
                if self.client.honor_session:
                    data[CONF_HONOR_SESSION] = self.client.honor_session
                self.hass.config_entries.async_update_entry(self.entry, data=data)
            return await self.client.async_get_status()
        except GritApiError as err:
            raise UpdateFailed(str(err)) from err
