"""Config flow for Honor Robot Cleaner."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import (
    GritApiClient,
    GritApiError,
    base_url_for_calling_code,
    parse_plugin_account_token,
)
from .const import (
    AUTH_MODE_PASSWORD,
    AUTH_MODE_TOKEN,
    CALLING_CODES,
    CONF_ACCOUNT,
    CONF_AUTH_MODE,
    CONF_BASE_URL,
    CONF_CALLING_CODE,
    CONF_DEVICE_ID,
    CONF_LANGUAGE,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SUB_TYPE,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_BASE_URL,
    DEFAULT_CALLING_CODE,
    DEFAULT_LANGUAGE,
    DEFAULT_NAME,
    DEFAULT_REGION,
    DEFAULT_SUB_TYPE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class HonorRobotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 2

    def __init__(self) -> None:
        self._client: GritApiClient | None = None
        self._session: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []
        self._auth_mode = AUTH_MODE_PASSWORD
        self._name = DEFAULT_NAME

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HonorRobotOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["login", "token"],
        )

    async def async_step_login(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            account = user_input[CONF_ACCOUNT].strip()
            password = user_input[CONF_PASSWORD]
            calling_code = user_input.get(CONF_CALLING_CODE, DEFAULT_CALLING_CODE)
            language = user_input.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
            self._name = user_input.get(CONF_NAME) or DEFAULT_NAME
            try:
                client = GritApiClient(
                    calling_code=calling_code,
                    language=language,
                    base_url=base_url_for_calling_code(calling_code),
                )
                session = await client.async_login_password(
                    account,
                    password,
                    calling_code=calling_code,
                    language=language,
                )
                devices = await client.async_list_devices()
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    self._client = client
                    self._session = {
                        **session,
                        CONF_PASSWORD: password,
                        CONF_AUTH_MODE: AUTH_MODE_PASSWORD,
                    }
                    self._devices = devices
                    self._auth_mode = AUTH_MODE_PASSWORD
                    if len(devices) == 1:
                        return await self._async_create_from_device(devices[0])
                    return await self.async_step_device()
            except GritApiError as err:
                _LOGGER.warning("Login failed: %s", err)
                msg = str(err)
                if "PasswordInvalid" in msg or "password" in msg.lower():
                    errors["base"] = "invalid_auth"
                elif "UserNotExist" in msg:
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Login failed")
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNT): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(
                    CONF_CALLING_CODE, default=DEFAULT_CALLING_CODE
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=k, label=f"{v} [{k}]")
                            for k, v in CALLING_CODES.items()
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )
        return self.async_show_form(step_id="login", data_schema=schema, errors=errors)

    async def async_step_token(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parsed = _normalize_token_credentials(user_input)
                client = GritApiClient(
                    token=parsed[CONF_TOKEN],
                    device_id=parsed.get(CONF_DEVICE_ID, ""),
                    region=parsed[CONF_REGION],
                    base_url=parsed[CONF_BASE_URL],
                    sub_type=parsed[CONF_SUB_TYPE],
                )
                devices = await client.async_list_devices()
                if parsed.get(CONF_DEVICE_ID):
                    match = [
                        d
                        for d in devices
                        if d.get("thing_name") == parsed[CONF_DEVICE_ID]
                    ]
                    if not match and devices:
                        # still allow explicit device even if list odd
                        match = [
                            {
                                "thing_name": parsed[CONF_DEVICE_ID],
                                "sub_type": parsed[CONF_SUB_TYPE],
                                "thing_nickname": user_input.get(CONF_NAME)
                                or DEFAULT_NAME,
                            }
                        ]
                    devices = match or devices
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    self._client = client
                    self._session = {
                        CONF_TOKEN: parsed[CONF_TOKEN],
                        CONF_REGION: parsed[CONF_REGION],
                        CONF_BASE_URL: parsed[CONF_BASE_URL],
                        CONF_AUTH_MODE: AUTH_MODE_TOKEN,
                    }
                    self._devices = devices
                    self._auth_mode = AUTH_MODE_TOKEN
                    self._name = user_input.get(CONF_NAME) or DEFAULT_NAME
                    if len(devices) == 1:
                        return await self._async_create_from_device(devices[0])
                    return await self.async_step_device()
            except ValueError:
                errors["base"] = "invalid_token_format"
            except GritApiError as err:
                _LOGGER.warning("Token login failed: %s", err)
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Token setup failed")
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD, multiline=True
                    )
                ),
                vol.Optional(CONF_DEVICE_ID): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Optional(CONF_REGION, default=DEFAULT_REGION): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                vol.Optional(CONF_SUB_TYPE, default=DEFAULT_SUB_TYPE): str,
            }
        )
        return self.async_show_form(step_id="token", data_schema=schema, errors=errors)

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        options = {
            d["thing_name"]: _device_label(d) for d in self._devices if d.get("thing_name")
        }
        if user_input is not None:
            thing = user_input[CONF_DEVICE_ID]
            device = next(d for d in self._devices if d.get("thing_name") == thing)
            return await self._async_create_from_device(device)

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=k, label=v)
                                for k, v in options.items()
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def _async_create_from_device(self, device: dict[str, Any]) -> FlowResult:
        assert self._client is not None
        device_id = device["thing_name"]
        sub_type = device.get("sub_type") or DEFAULT_SUB_TYPE
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()

        self._client.device_id = device_id
        self._client.sub_type = sub_type
        await self._client.async_get_status()

        title = (
            device.get("thing_nickname")
            or self._name
            or DEFAULT_NAME
        )
        data = {
            CONF_TOKEN: self._client.token,
            CONF_DEVICE_ID: device_id,
            CONF_REGION: self._client.region,
            CONF_BASE_URL: self._client.base_url,
            CONF_SUB_TYPE: sub_type,
            CONF_NAME: title,
            CONF_AUTH_MODE: self._auth_mode,
            CONF_TOKEN_EXPIRES_AT: self._client.token_expires_at,
        }
        if self._auth_mode == AUTH_MODE_PASSWORD:
            data.update(
                {
                    CONF_ACCOUNT: self._session.get(CONF_ACCOUNT)
                    or self._client.account,
                    CONF_PASSWORD: self._session[CONF_PASSWORD],
                    CONF_CALLING_CODE: self._client.calling_code,
                    CONF_LANGUAGE: self._client.language,
                }
            )
        return self.async_create_entry(title=title, data=data)


class HonorRobotOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Update credentials / re-login."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        current = {**self.config_entry.data, **self.options}
        if current.get(CONF_AUTH_MODE) == AUTH_MODE_PASSWORD or current.get(CONF_ACCOUNT):
            return await self.async_step_password()
        return await self.async_step_token()

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.options}
        if user_input is not None:
            try:
                client = GritApiClient(
                    device_id=current[CONF_DEVICE_ID],
                    sub_type=current.get(CONF_SUB_TYPE, DEFAULT_SUB_TYPE),
                    calling_code=user_input.get(
                        CONF_CALLING_CODE, current.get(CONF_CALLING_CODE, DEFAULT_CALLING_CODE)
                    ),
                    language=user_input.get(
                        CONF_LANGUAGE, current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
                    ),
                )
                await client.async_login_password(
                    user_input[CONF_ACCOUNT],
                    user_input[CONF_PASSWORD],
                )
                client.device_id = current[CONF_DEVICE_ID]
                client.sub_type = current.get(CONF_SUB_TYPE, DEFAULT_SUB_TYPE)
                await client.async_get_status()
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_ACCOUNT: user_input[CONF_ACCOUNT],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_CALLING_CODE: client.calling_code,
                        CONF_LANGUAGE: client.language,
                        CONF_TOKEN: client.token,
                        CONF_REGION: client.region,
                        CONF_BASE_URL: client.base_url,
                        CONF_DEVICE_ID: current[CONF_DEVICE_ID],
                        CONF_SUB_TYPE: current.get(CONF_SUB_TYPE, DEFAULT_SUB_TYPE),
                        CONF_AUTH_MODE: AUTH_MODE_PASSWORD,
                        CONF_TOKEN_EXPIRES_AT: client.token_expires_at,
                    },
                )
            except GritApiError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Options re-login failed")
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ACCOUNT, default=current.get(CONF_ACCOUNT, "")
                ): str,
                vol.Required(
                    CONF_PASSWORD, default=current.get(CONF_PASSWORD, "")
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(
                    CONF_CALLING_CODE,
                    default=current.get(CONF_CALLING_CODE, DEFAULT_CALLING_CODE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=k, label=f"{v} [{k}]")
                            for k, v in CALLING_CODES.items()
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_LANGUAGE,
                    default=current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="password", data_schema=schema, errors=errors
        )

    async def async_step_token(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.options}
        if user_input is not None:
            try:
                merged = {**current, **user_input}
                parsed = _normalize_token_credentials(merged)
                client = GritApiClient(
                    token=parsed[CONF_TOKEN],
                    device_id=parsed[CONF_DEVICE_ID],
                    region=parsed[CONF_REGION],
                    base_url=parsed[CONF_BASE_URL],
                    sub_type=parsed[CONF_SUB_TYPE],
                )
                await client.async_get_status()
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_TOKEN: parsed[CONF_TOKEN],
                        CONF_DEVICE_ID: parsed[CONF_DEVICE_ID],
                        CONF_REGION: parsed[CONF_REGION],
                        CONF_BASE_URL: parsed[CONF_BASE_URL],
                        CONF_SUB_TYPE: parsed[CONF_SUB_TYPE],
                        CONF_AUTH_MODE: AUTH_MODE_TOKEN,
                    },
                )
            except ValueError:
                errors["base"] = "invalid_token_format"
            except GritApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Options token update failed")
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TOKEN, default=current.get(CONF_TOKEN, "")
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD, multiline=True
                    )
                ),
                vol.Optional(
                    CONF_DEVICE_ID, default=current.get(CONF_DEVICE_ID, "")
                ): str,
                vol.Optional(
                    CONF_REGION, default=current.get(CONF_REGION, DEFAULT_REGION)
                ): str,
                vol.Optional(
                    CONF_BASE_URL, default=current.get(CONF_BASE_URL, DEFAULT_BASE_URL)
                ): str,
                vol.Optional(
                    CONF_SUB_TYPE, default=current.get(CONF_SUB_TYPE, DEFAULT_SUB_TYPE)
                ): str,
            }
        )
        return self.async_show_form(step_id="token", data_schema=schema, errors=errors)


def _device_label(device: dict[str, Any]) -> str:
    nick = device.get("thing_nickname") or "Robot"
    thing = device.get("thing_name", "")
    sub = device.get("sub_type") or ""
    return f"{nick} ({sub}) — {thing[-8:]}"


def _normalize_token_credentials(user_input: dict[str, Any]) -> dict[str, str]:
    token_raw = (user_input.get(CONF_TOKEN) or "").strip()
    device_id = (user_input.get(CONF_DEVICE_ID) or "").strip()
    region = (user_input.get(CONF_REGION) or DEFAULT_REGION).strip()
    base_url = (user_input.get(CONF_BASE_URL) or DEFAULT_BASE_URL).strip()
    sub_type = (user_input.get(CONF_SUB_TYPE) or DEFAULT_SUB_TYPE).strip()

    if ";" in token_raw:
        parsed = parse_plugin_account_token(token_raw)
        token = parsed["token"]
        device_id = device_id or parsed["device_id"]
        region = parsed.get("region") or region
        base_url = parsed.get("base_url") or base_url
    else:
        token = token_raw

    if not token:
        raise ValueError("token required")

    if not base_url.endswith("/"):
        base_url += "/"

    return {
        CONF_TOKEN: token,
        CONF_DEVICE_ID: device_id,
        CONF_REGION: region,
        CONF_BASE_URL: base_url,
        CONF_SUB_TYPE: sub_type,
    }
