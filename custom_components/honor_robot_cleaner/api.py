"""YuGong / Grit cloud API client for Honor Choice robot cleaners."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .const import (
    APP_NAME,
    APP_SECRET,
    BUNDLE_ID,
    CLIENT_ID,
    CMD_CONTINUE,
    CMD_DOCK,
    CMD_PAUSE,
    CMD_SPOT,
    CMD_START,
    CMD_STOP,
    DEFAULT_APP_VERSION,
    DEFAULT_BASE_URL,
    DEFAULT_BASE_URL_CN,
    DEFAULT_CALLING_CODE,
    DEFAULT_LANGUAGE,
    DEFAULT_REGION,
)

_LOGGER = logging.getLogger(__name__)


class GritApiError(Exception):
    """API returned a non-success payload or transport failed."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def base_url_for_calling_code(calling_code: str) -> str:
    if (calling_code or "").strip() == "0086":
        return DEFAULT_BASE_URL_CN
    return DEFAULT_BASE_URL


class GritApiClient:
    """Async wrapper around the Honour Grit HTTP API."""

    def __init__(
        self,
        *,
        token: str = "",
        device_id: str = "",
        region: str = DEFAULT_REGION,
        base_url: str = DEFAULT_BASE_URL,
        sub_type: str = "rob-01",
        account: str = "",
        password: str = "",
        calling_code: str = DEFAULT_CALLING_CODE,
        language: str = DEFAULT_LANGUAGE,
        token_expires_at: float | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.token = (token or "").strip()
        self.device_id = (device_id or "").strip()
        self.region = (region or DEFAULT_REGION).strip()
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/"
        self.sub_type = (sub_type or "rob-01").strip()
        self.account = (account or "").strip()
        self.password = password or ""
        self.calling_code = (calling_code or DEFAULT_CALLING_CODE).strip()
        self.language = (language or DEFAULT_LANGUAGE).strip()
        self.token_expires_at = token_expires_at
        self.timeout = timeout

    def update_from_dict(self, data: dict[str, Any]) -> None:
        mapping = {
            "token": "token",
            "device_id": "device_id",
            "region": "region",
            "base_url": "base_url",
            "sub_type": "sub_type",
            "account": "account",
            "password": "password",
            "calling_code": "calling_code",
            "language": "language",
            "token_expires_at": "token_expires_at",
        }
        for src, attr in mapping.items():
            if src in data and data[src] is not None:
                value = data[src]
                if attr == "base_url":
                    value = str(value).rstrip("/") + "/"
                setattr(self, attr, value)

    def _auth_header(self) -> dict[str, str]:
        return {
            "app_version": DEFAULT_APP_VERSION,
            "app_name": APP_NAME,
            "calling_code": self.calling_code,
            "account": self.account or "null",
            "language": self.language,
            "client_id": CLIENT_ID,
        }

    async def async_post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        token: str | None = None,
        region: str | None = None,
        use_api_headers: bool = False,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._post,
            path,
            body,
            token,
            region,
            use_api_headers,
        )

    def _post(
        self,
        path: str,
        body: dict[str, Any],
        token: str | None,
        region: str | None,
        use_api_headers: bool,
    ) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        url = self.base_url + path.lstrip("/")
        req = Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if use_api_headers:
            req.add_header("token", token if token is not None else self.token)
            req.add_header("region", region if region is not None else self.region)
        elif token:
            req.add_header("token", token)

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

    async def async_verify_app(self) -> str:
        payload = await self.async_post(
            "oauth2",
            {
                "header": self._auth_header(),
                "payload": {
                    "opt": "verify_app",
                    "app_secret": APP_SECRET,
                    "app_name": APP_NAME,
                    "bundle_id": BUNDLE_ID,
                },
            },
        )
        token = (payload.get("data") or {}).get("token")
        if not token:
            raise GritApiError("verify_app returned no token")
        return token

    async def async_login_password(
        self,
        account: str,
        password: str,
        *,
        calling_code: str | None = None,
        language: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Login with phone/email + password. Returns session fields."""
        self.account = account.strip()
        self.password = password
        if calling_code:
            self.calling_code = calling_code.strip()
        if language:
            self.language = language.strip()
        if base_url:
            self.base_url = base_url.rstrip("/") + "/"
        else:
            self.base_url = base_url_for_calling_code(self.calling_code)

        app_token = await self.async_verify_app()
        header = self._auth_header()
        header["account"] = self.account
        payload = await self.async_post(
            "oauth2",
            {
                "header": header,
                "payload": {"opt": "login", "pwd": self.password},
            },
            token=app_token,
        )
        data = payload.get("data") or {}
        token = data.get("token")
        if not token:
            raise GritApiError("login returned no token")

        self.token = token
        if data.get("region_name"):
            self.region = data["region_name"]
        if data.get("api_url"):
            self.base_url = str(data["api_url"]).rstrip("/") + "/"
        expired = data.get("expired_time")
        if expired is not None:
            self.token_expires_at = time.time() + float(expired)
        else:
            self.token_expires_at = time.time() + 20 * 3600

        return {
            "token": self.token,
            "region": self.region,
            "base_url": self.base_url,
            "wss_url": data.get("wss_url"),
            "token_expires_at": self.token_expires_at,
            "account": self.account,
            "calling_code": self.calling_code,
            "language": self.language,
        }

    async def async_ensure_token(self, skew: int = 600) -> bool:
        """Re-login if password auth and token is missing/expiring. Returns True if refreshed."""
        if not self.account or not self.password:
            return False
        needs = not self.token
        if self.token_expires_at is not None and time.time() >= (
            float(self.token_expires_at) - skew
        ):
            needs = True
        if not needs:
            return False
        _LOGGER.info("Refreshing Grit session for %s", self.account)
        await self.async_login_password(
            self.account,
            self.password,
            calling_code=self.calling_code,
            language=self.language,
            base_url=self.base_url,
        )
        return True

    async def async_request(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.async_post(
                "api", body, use_api_headers=True
            )
        except GritApiError as err:
            msg = str(err).lower()
            if self.account and self.password and (
                "token" in msg or err.code in (0, None)
            ):
                await self.async_login_password(
                    self.account,
                    self.password,
                    calling_code=self.calling_code,
                    language=self.language,
                    base_url=self.base_url,
                )
                return await self.async_post("api", body, use_api_headers=True)
            raise

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
