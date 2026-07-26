"""YuGong / Grit cloud API client for Honor Choice robot cleaners."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .const import (
    CMD_CONTINUE,
    CMD_DOCK,
    CMD_PAUSE,
    CMD_SPOT,
    CMD_START,
    CMD_STOP,
)

_LOGGER = logging.getLogger(__name__)


class GritApiError(Exception):
    """API returned a non-success payload or transport failed."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class GritApiClient:
    """Minimal async wrapper around the Honour Grit HTTP API."""

    def __init__(
        self,
        token: str,
        device_id: str,
        *,
        region: str,
        base_url: str,
        sub_type: str,
        timeout: float = 20.0,
    ) -> None:
        self.token = token.strip()
        self.device_id = device_id.strip()
        self.region = region.strip()
        self.base_url = base_url.rstrip("/") + "/"
        self.sub_type = sub_type.strip()
        self.timeout = timeout

    def update_credentials(
        self,
        *,
        token: str | None = None,
        device_id: str | None = None,
        region: str | None = None,
        base_url: str | None = None,
        sub_type: str | None = None,
    ) -> None:
        if token is not None:
            self.token = token.strip()
        if device_id is not None:
            self.device_id = device_id.strip()
        if region is not None:
            self.region = region.strip()
        if base_url is not None:
            self.base_url = base_url.rstrip("/") + "/"
        if sub_type is not None:
            self.sub_type = sub_type.strip()

    async def async_request(self, body: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, body)

    def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = Request(self.base_url + "api", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("token", self.token)
        req.add_header("region", self.region)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            raise GritApiError(f"HTTP {err.code}: {detail}") from err
        except URLError as err:
            raise GritApiError(f"Network error: {err.reason}") from err

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as err:
            raise GritApiError(f"Invalid JSON: {raw[:200]}") from err

        if payload.get("code") != 1:
            raise GritApiError(
                payload.get("msg") or "Unknown API error",
                code=payload.get("code"),
            )
        return payload

    async def async_get_status(self) -> dict[str, Any]:
        payload = await self.async_request(
            {
                "opt": "sync_thing_status",
                "sub_type": self.sub_type,
                "thing_name": self.device_id,
            }
        )
        data = payload.get("data") or {}
        status = data.get("thing_status") or {}
        if not status:
            raise GritApiError("Empty thing_status in response")
        return status

    async def async_list_devices(self) -> list[dict[str, Any]]:
        payload = await self.async_request({"opt": "user_thing_list_get"})
        data = payload.get("data") or {}
        return list(data.get("thing_list") or [])

    async def async_send_working_status(self, working_status: str) -> None:
        await self.async_request(
            {
                "opt": "send_to_device",
                "sub_type": self.sub_type,
                "thing_name": self.device_id,
                "topic_payload": {"state": {"working_status": working_status}},
            }
        )

    async def async_set_fan_status(self, fan_status: str) -> None:
        await self.async_request(
            {
                "opt": "send_to_device",
                "sub_type": self.sub_type,
                "thing_name": self.device_id,
                "topic_payload": {"state": {"fan_status": fan_status}},
            }
        )

    async def async_start(self) -> None:
        await self.async_send_working_status(CMD_START)

    async def async_pause(self) -> None:
        await self.async_send_working_status(CMD_PAUSE)

    async def async_continue(self) -> None:
        await self.async_send_working_status(CMD_CONTINUE)

    async def async_stop(self) -> None:
        await self.async_send_working_status(CMD_STOP)

    async def async_return_to_base(self) -> None:
        await self.async_send_working_status(CMD_DOCK)

    async def async_spot(self) -> None:
        await self.async_send_working_status(CMD_SPOT)


def parse_plugin_account_token(raw: str) -> dict[str, str]:
    """Parse Honor AI Space plugin_account.xml token field.

    Format: device_id;JWT;region;lang;expiry_ms;https_base;wss_base
    """
    parts = [p.strip() for p in raw.strip().split(";")]
    if len(parts) < 6:
        raise ValueError(
            "Expected plugin_account token: device;jwt;region;lang;exp;https;[wss]"
        )
    device_id, jwt, region, _lang, _exp, base_url = parts[:6]
    if not jwt or jwt.count(".") != 2:
        raise ValueError("JWT part looks invalid")
    result = {
        "device_id": device_id,
        "token": jwt,
        "region": region,
        "base_url": base_url if base_url.endswith("/") else base_url + "/",
    }
    if len(parts) >= 7:
        result["wss_url"] = parts[6]
    return result
