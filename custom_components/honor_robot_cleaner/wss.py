"""YuGong / Grit WebSocket channel — live map_data + thing_status_update."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .api import GritApiClient

_LOGGER = logging.getLogger(__name__)

NOTIFY_MAP = "map_data"
NOTIFY_STATUS = "thing_status_update"
NOTIFY_ZONE = "zone_cmd_rsp"
NOTIFY_ZONE_SAVE = "zone_info_save"
HEARTBEAT_SECONDS = 2.0
RECONNECT_MIN = 2.0
RECONNECT_MAX = 60.0

StatusHandler = Callable[[dict[str, Any]], Awaitable[None] | None]
MapHandler = Callable[[str], Awaitable[None] | None]
ZoneHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


def wss_url_from_base(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.startswith("https://"):
        return base.replace("https://", "wss://", 1) + "/wss"
    if base.startswith("http://"):
        return base.replace("http://", "ws://", 1) + "/wss"
    return "wss://honour.grit-cloud.com/prod/wss"


class GritWssClient:
    """Keep a cloud WSS session open and dispatch map/status notifies."""

    def __init__(
        self,
        client: GritApiClient,
        *,
        on_status: StatusHandler | None = None,
        on_map: MapHandler | None = None,
        on_zone: ZoneHandler | None = None,
        wss_url: str | None = None,
    ) -> None:
        self._client = client
        self._on_status = on_status
        self._on_map = on_map
        self._on_zone = on_zone
        self._wss_url = (wss_url or "").strip() or None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.connected = False
        self.last_error: str | None = None

    @property
    def url(self) -> str:
        if self._wss_url:
            return self._wss_url
        if getattr(self._client, "wss_url", None):
            return str(self._client.wss_url)
        return wss_url_from_base(self._client.base_url)

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="honor_robot_wss")

    async def async_stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.connected = False

    async def _run(self) -> None:
        delay = RECONNECT_MIN
        while not self._stop.is_set():
            try:
                await self._client.async_ensure_token()
                await self._session_loop()
                delay = RECONNECT_MIN
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                self.connected = False
                self.last_error = str(err)
                _LOGGER.warning("WSS disconnected: %s — retry in %.0fs", err, delay)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                    break
                except asyncio.TimeoutError:
                    delay = min(delay * 2, RECONNECT_MAX)

    async def _session_loop(self) -> None:
        url = self.url
        headers = {
            "token": self._client.token,
            "region": self._client.region,
            "User-Agent": "okhttp/3.12.1",
        }
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None)
        _LOGGER.info("WSS connecting %s", url)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                url,
                headers=headers,
                heartbeat=None,
                autoping=False,
            ) as ws:
                self.connected = True
                self.last_error = None
                _LOGGER.info("WSS connected")
                sync = {
                    "opt": "sync_thing",
                    "sub_type": self._client.sub_type,
                    "thing_name": self._client.device_id,
                }
                await ws.send_str(json.dumps(sync))
                # Ask for room polygons once per session
                try:
                    await self._client.async_request_room_info()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("req_zone_info failed", exc_info=True)
                while not self._stop.is_set():
                    try:
                        msg = await asyncio.wait_for(
                            ws.receive(), timeout=HEARTBEAT_SECONDS
                        )
                    except asyncio.TimeoutError:
                        if ws.closed:
                            raise ConnectionError("WSS closed during heartbeat")
                        await ws.send_str(json.dumps(sync))
                        continue

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_text(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        try:
                            await self._handle_text(msg.data.decode("utf-8", "replace"))
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug("Ignoring binary WSS frame")
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSED,
                    ):
                        raise ConnectionError("WSS closed by peer")
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        raise ConnectionError(f"WSS error: {ws.exception()}")

        self.connected = False

    async def _handle_text(self, text: str) -> None:
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            _LOGGER.debug("Non-JSON WSS frame (%s bytes)", len(text))
            return
        if not isinstance(obj, dict):
            return

        notify = obj.get("notify_info")
        thing = obj.get("thing_name")
        if thing and self._client.device_id and thing != self._client.device_id:
            return

        if notify == NOTIFY_MAP:
            map_data = obj.get("map_data")
            if isinstance(map_data, str) and map_data and self._on_map:
                result = self._on_map(map_data)
                if asyncio.iscoroutine(result):
                    await result
            return

        if notify == NOTIFY_STATUS:
            status = obj.get("thing_status")
            if isinstance(status, dict) and self._on_status:
                result = self._on_status(status)
                if asyncio.iscoroutine(result):
                    await result
            return

        if notify in (NOTIFY_ZONE, NOTIFY_ZONE_SAVE) and self._on_zone:
            result = self._on_zone(obj)
            if asyncio.iscoroutine(result):
                await result
            return
