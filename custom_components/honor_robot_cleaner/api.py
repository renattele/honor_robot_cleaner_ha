"""YuGong / Grit cloud API client for Honor Choice robot cleaners."""

from __future__ import annotations

import asyncio
import http.client
import json
import logging
import ssl
import time
from typing import Any
from urllib.parse import urlparse

from .const import (
    APP_NAME,
    APP_SECRET,
    AUTH_MODE_HONOR,
    AUTH_MODE_PASSWORD,
    AUTH_MODE_TOKEN,
    BUNDLE_ID,
    CLIENT_ID,
    CMD_CLEAR_MAP,
    CMD_CONTINUE,
    CMD_DOCK,
    CMD_LOCATE,
    CMD_MOVE_BACK,
    CMD_MOVE_FRONT,
    CMD_MOVE_LEFT,
    CMD_MOVE_RIGHT,
    CMD_MOVE_STOP,
    CMD_PAUSE,
    CMD_SELECT_CLEAN,
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


def jwt_expires_at(token: str) -> float | None:
    """Return JWT ``exp`` as unix seconds, or None if missing/invalid."""
    try:
        parts = (token or "").strip().split(".")
        if len(parts) != 3:
            return None
        import base64

        pad = "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        exp = payload.get("exp")
        return float(exp) if exp is not None else None
    except Exception:  # noqa: BLE001
        return None


def _http_post_json(
    url: str,
    body: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, str]:
    """POST JSON preserving header name case.

    CPython ``urllib.request`` title-cases headers (``token`` → ``Token``).
    Grit ``oauth2`` auth is case-sensitive and rejects ``Token``.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise GritApiError(f"Unsupported URL scheme: {parsed.scheme}")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    data = json.dumps(body).encode("utf-8")
    conn = http.client.HTTPSConnection(
        parsed.hostname,
        parsed.port or 443,
        timeout=timeout,
        context=ssl.create_default_context(),
    )
    try:
        conn.request("POST", path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        return resp.status, raw
    except TimeoutError as err:
        raise GritApiError(f"Network error: timed out") from err
    except OSError as err:
        raise GritApiError(f"Network error: {err}") from err
    finally:
        conn.close()


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
        auth_mode: str = AUTH_MODE_TOKEN,
        honor_session: dict[str, Any] | None = None,
        wss_url: str = "",
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
        self.auth_mode = (auth_mode or AUTH_MODE_TOKEN).strip()
        self.honor_session = dict(honor_session or {})
        self.token_expires_at = token_expires_at
        self.wss_url = (wss_url or "").strip()
        self.timeout = timeout
        self.sync_token_expiry()

    def sync_token_expiry(self) -> None:
        """Fill ``token_expires_at`` from JWT when missing or stale."""
        exp = jwt_expires_at(self.token)
        if exp is not None:
            self.token_expires_at = exp

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
            "auth_mode": "auth_mode",
            "honor_session": "honor_session",
            "wss_url": "wss_url",
        }
        for src, attr in mapping.items():
            if src in data and data[src] is not None:
                value = data[src]
                if attr == "base_url":
                    value = str(value).rstrip("/") + "/"
                if attr == "honor_session" and not isinstance(value, dict):
                    continue
                setattr(self, attr, value)
        if "token" in data:
            self.sync_token_expiry()

    def resolve_wss_url(self) -> str:
        if self.wss_url:
            return self.wss_url
        from .wss import wss_url_from_base

        return wss_url_from_base(self.base_url)

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
        url = self.base_url + path.lstrip("/")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "okhttp/3.12.1",
        }
        if use_api_headers:
            headers["token"] = token if token is not None else self.token
            headers["region"] = region if region is not None else self.region
        elif token:
            headers["token"] = token

        status, raw = _http_post_json(
            url, body, headers=headers, timeout=self.timeout
        )
        if status >= 400:
            raise GritApiError(f"HTTP {status}: {raw}")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as err:
            raise GritApiError(f"Invalid JSON: {raw[:200]}") from err

        if payload.get("code") != 1:
            raise GritApiError(
                payload.get("msg") or "Unknown API error",
                code=payload.get("code"),
            )
        # Honor sometimes returns code=1 with a stringified error in data
        data = payload.get("data")
        if isinstance(data, str):
            stripped = data.strip().strip("'\"")
            if (
                "error" in data
                or "sub_error" in data
                or "invalid" in data.lower()
                or stripped in {"thing_name", "auth_code", "sub_type", "token"}
            ):
                raise GritApiError(data, code=payload.get("code"))
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

    async def async_login_honor_auth_code(
        self,
        auth_code: str,
        *,
        device_id: str | None = None,
        sub_type: str | None = None,
        calling_code: str | None = None,
        language: str | None = None,
        system_id: str = "android_ha",
        is_admin: bool = True,
        family_name: str = "Home",
        room_name: str = "Room",
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Honor AI Space login: Honor ID auth_code → Grit JWT (honor_card_login).

        Flow in yxseeper:
          1) MagicHome silentThirdSignIn(clientId=221000090) → auth_code
          2) verify_app → app JWT
          3) oauth2 honor_card_login(auth_code, thing_name=deviceId, ...)
        """
        auth_code = (auth_code or "").strip()
        if not auth_code:
            raise GritApiError("Empty Honor auth_code")
        if device_id is not None:
            self.device_id = device_id.strip()
        if sub_type:
            self.sub_type = sub_type.strip()
        if calling_code:
            self.calling_code = calling_code.strip()
        if language:
            self.language = language.strip()
        if base_url:
            self.base_url = base_url.rstrip("/") + "/"
        else:
            self.base_url = base_url_for_calling_code(self.calling_code)

        app_token = await self.async_verify_app()
        if not (self.device_id or "").strip():
            raise GritApiError(
                "honor_card_login requires thing_name (robot device id); "
                "empty thing_name causes Put_Table_Error"
            )
        # Magichome always sends thing_name (= device id) + android_* system_id.
        payload = await self.async_post(
            "oauth2",
            {
                "header": {
                    "app_version": DEFAULT_APP_VERSION,
                    "app_name": APP_NAME,
                },
                "payload": {
                    "opt": "honor_card_login",
                    "auth_code": auth_code,
                    "thing_name": self.device_id,
                    "sub_type": self.sub_type or "rob-01",
                    "calling_code": self.calling_code,
                    "language": self.language,
                    "system_id": system_id,
                    "is_admin": bool(is_admin),
                    "family_name": family_name,
                    "room_name": room_name,
                },
            },
            token=app_token,
        )
        data = payload.get("data") or {}
        if isinstance(data, str):
            # API sometimes returns code=1 with data="'thing_name'" for missing fields
            raise GritApiError(f"honor_card_login rejected: {data}")
        if not isinstance(data, dict):
            raise GritApiError(f"honor_card_login bad data: {data!r}")
        # Response field is card_token (YuGongRespDataLoginWithAuthCode)
        token = data.get("card_token") or data.get("token")
        if not token:
            raise GritApiError("honor_card_login returned no card_token")

        self.token = token
        if data.get("region_name"):
            self.region = data["region_name"]
        if data.get("api_url"):
            api_url = str(data["api_url"])
            if api_url.endswith("api"):
                api_url = api_url[: api_url.index("api")]
            self.base_url = api_url.rstrip("/") + "/"
        expired = data.get("expired_time")
        if expired is not None:
            self.token_expires_at = time.time() + float(expired)
        else:
            self.sync_token_expiry()
            if self.token_expires_at is None:
                self.token_expires_at = time.time() + 20 * 3600
        self.auth_mode = AUTH_MODE_HONOR
        if data.get("wss_url"):
            self.wss_url = str(data["wss_url"])

        return {
            "token": self.token,
            "region": self.region,
            "base_url": self.base_url,
            "wss_url": data.get("wss_url") or self.wss_url,
            "token_expires_at": self.token_expires_at,
            "device_id": self.device_id,
            "sub_type": self.sub_type,
            "calling_code": self.calling_code,
            "language": self.language,
            "auth_mode": AUTH_MODE_HONOR,
        }

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
            self.sync_token_expiry()
            if self.token_expires_at is None:
                self.token_expires_at = time.time() + 20 * 3600
        self.auth_mode = AUTH_MODE_PASSWORD
        if data.get("wss_url"):
            self.wss_url = str(data["wss_url"])

        return {
            "token": self.token,
            "region": self.region,
            "base_url": self.base_url,
            "wss_url": data.get("wss_url") or self.wss_url,
            "token_expires_at": self.token_expires_at,
            "account": self.account,
            "calling_code": self.calling_code,
            "language": self.language,
        }

    def token_needs_refresh(self, skew: int = 600) -> bool:
        self.sync_token_expiry()
        if not self.token:
            return True
        if self.token_expires_at is None:
            return False
        return time.time() >= (float(self.token_expires_at) - skew)

    async def async_refresh_honor_session(self) -> bool:
        """Silent Honor SSO → new auth_code → honor_card_login (no phone/adb)."""
        from .honor_id import HonorIdClient, HonorIdError

        if not self.honor_session:
            raise GritApiError(
                "No Honor session stored. Re-add the integration via "
                "Honor AI Space login (phone + password + SMS)."
            )
        if not self.device_id:
            raise GritApiError("device_id required for Honor token refresh")

        def _silent() -> tuple[str, dict]:
            hid = HonorIdClient()
            hid.import_session(self.honor_session)
            return hid.refresh_auth_code()

        try:
            auth_code, session = await asyncio.to_thread(_silent)
        except HonorIdError as err:
            raise GritApiError(str(err)) from err

        self.honor_session = session
        await self.async_login_honor_auth_code(
            auth_code,
            device_id=self.device_id,
            sub_type=self.sub_type,
            calling_code=self.calling_code,
            language=self.language,
        )
        return True

    async def async_ensure_token(
        self, skew: int = 600, *, force: bool = False
    ) -> bool:
        """Refresh JWT when missing/expiring. Returns True if refreshed."""
        if not force and not self.token_needs_refresh(skew):
            return False

        mode = self.auth_mode or AUTH_MODE_TOKEN
        _LOGGER.info(
            "Refreshing Grit token (mode=%s, honor_session=%s)",
            mode,
            "yes" if self.honor_session else "no",
        )

        if mode == AUTH_MODE_PASSWORD and self.account and self.password:
            await self.async_login_password(
                self.account,
                self.password,
                calling_code=self.calling_code,
                language=self.language,
                base_url=self.base_url,
            )
            return True

        if mode == AUTH_MODE_HONOR or self.honor_session:
            await self.async_refresh_honor_session()
            return True

        if mode == AUTH_MODE_PASSWORD:
            raise GritApiError("Password missing for token refresh")

        raise GritApiError(
            "Token expired. Use Honor AI Space login (stores a refreshable "
            "Honor session) or YuGong password login."
        )

    async def async_request(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.async_post(
                "api", body, use_api_headers=True
            )
        except GritApiError as err:
            msg = str(err).lower()
            tokenish = (
                "token" in msg
                or "unauthorized" in msg
                or "http 401" in msg
                or "http 403" in msg
                or "TokenInValid" in str(err)
                or "TokenInvalid" in str(err)
            )
            if tokenish:
                try:
                    await self.async_ensure_token(force=True)
                except GritApiError:
                    raise err from None
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

    async def async_send_state(self, **state: Any) -> None:
        """Send topic_payload.state fields via send_to_device."""
        await self.async_request(
            {
                "opt": "send_to_device",
                "sub_type": self.sub_type,
                "thing_name": self.device_id,
                "topic_payload": {"state": dict(state)},
            }
        )

    async def async_send_working_status(self, working_status: str) -> None:
        await self.async_send_state(working_status=working_status)

    async def async_set_fan_status(self, fan_status: str) -> None:
        await self.async_send_state(fan_status=fan_status)

    async def async_set_water_level(self, water_level: str) -> None:
        await self.async_send_state(water_level=water_level)

    async def async_set_volume(self, volume: int) -> None:
        await self.async_send_state(volume=int(volume))

    async def async_set_light(self, light_on: bool) -> None:
        await self.async_send_state(light_on=bool(light_on))

    async def async_set_carpet_fan_boost(self, enabled: bool) -> None:
        await self.async_send_state(carpet_fan_boost=bool(enabled))

    async def async_set_continue_clean(self, enabled: bool) -> None:
        await self.async_send_state(continue_clean=bool(enabled))

    async def async_set_undisturb_mode(self, enabled: bool) -> None:
        await self.async_send_state(undisturb_mode="on" if enabled else "off")

    async def async_set_zone_policy(self, enabled: bool) -> None:
        await self.async_send_state(zone_policy_enable=bool(enabled))

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

    async def async_locate(self) -> None:
        await self.async_send_working_status(CMD_LOCATE)

    async def async_move(self, direction: str) -> None:
        await self.async_send_working_status(direction)

    async def async_move_front(self) -> None:
        await self.async_move(CMD_MOVE_FRONT)

    async def async_move_back(self) -> None:
        await self.async_move(CMD_MOVE_BACK)

    async def async_move_left(self) -> None:
        await self.async_move(CMD_MOVE_LEFT)

    async def async_move_right(self) -> None:
        await self.async_move(CMD_MOVE_RIGHT)

    async def async_move_stop(self) -> None:
        await self.async_move(CMD_MOVE_STOP)

    async def async_request_room_info(self) -> None:
        """Ask device for room polygons via zone_info_cmd (response on WSS)."""
        await self.async_request(
            {
                "opt": "send_to_device",
                "sub_type": self.sub_type,
                "thing_name": self.device_id,
                "topic_payload": {
                    "state": {
                        "zone_info_cmd": {
                            "cmd": "req_zone_info",
                            "data": [{"zone_type": "useto_edit"}],
                            "extend": {},
                        }
                    }
                },
            }
        )

    async def async_clear_map(self) -> None:
        await self.async_send_working_status(CMD_CLEAR_MAP)

    async def async_clean_rooms(
        self, room_ids: list[int], *, times: int = 1
    ) -> None:
        zones = [
            {"room_id": int(rid), "times": int(times)} for rid in room_ids
        ]
        await self.async_send_state(
            working_status=CMD_SELECT_CLEAN,
            selected_zone=zones,
        )

    async def async_list_maps(self) -> dict[str, Any]:
        payload = await self.async_request(
            {
                "opt": "reuse_map_list_get",
                "sub_type": self.sub_type,
                "thing_name": self.device_id,
            }
        )
        return payload.get("data") or {}

    async def async_get_map(self, map_id: str) -> dict[str, Any]:
        payload = await self.async_request(
            {
                "opt": "reuse_map_get",
                "sub_type": self.sub_type,
                "thing_name": self.device_id,
                "map_id": str(map_id),
            }
        )
        return payload.get("data") or {}

    async def async_enable_map(self, map_id: str, map_name: str = "") -> None:
        body: dict[str, Any] = {
            "opt": "reuse_map_enable",
            "sub_type": self.sub_type,
            "thing_name": self.device_id,
            "map_id": str(map_id),
        }
        if map_name:
            body["map_name"] = map_name
        await self.async_request(body)


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
