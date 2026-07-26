"""DataUpdateCoordinator for Honor Robot Cleaner."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GritApiClient, GritApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

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
            return await self.client.async_get_status()
        except GritApiError as err:
            raise UpdateFailed(str(err)) from err
