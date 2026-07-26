"""Config flow for Honor Robot Cleaner."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.network import get_url

from .const import (
    AUTH_MODE_HONOR,
    AUTH_MODE_PASSWORD,
    AUTH_MODE_TOKEN,
    CALLING_CODES,
    CONF_ACCOUNT,
        CONF_AUTH_MODE,
    CONF_BASE_URL,
    CONF_CALLING_CODE,
    CONF_DEVICE_ID,
    CONF_HONOR_SESSION,
    CONF_LANGUAGE,
    CONF_NAME,
    CONF_PASSWORD,
        CONF_REGION,
    CONF_SMS_CODE,
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
from .api import (
    GritApiClient,
    GritApiError,
    base_url_for_calling_code,
    jwt_expires_at,
    parse_plugin_account_token,
)
from .honor_id import HonorIdClient, HonorIdError
from .http_captcha import (
    async_get_captcha_validate,
    async_pop_captcha_session,
    async_put_captcha_session,
)

_LOGGER = logging.getLogger(__name__)


def _classify_grit_error(err: GritApiError) -> str:
    """Map API failures to config-flow error keys."""
    msg = str(err)
    lower = msg.lower()
    if "network error" in lower or "timed out" in lower or "timeout" in lower:
        return "cannot_connect"
    if any(
        s in msg
        for s in (
            "PasswordInvalid",
            "UserNotExist",
            "TokenInvalid",
            "Unauthorized",
            "AccessDenied",
            "not authorized",
            "explicit deny",
        )
    ):
        return "invalid_auth"
    if "HTTP 401" in msg or "HTTP 403" in msg:
        return "invalid_auth"
    if "password" in lower:
        return "invalid_auth"
    return "unknown"


def _classify_honor_error(err: HonorIdError) -> str:
    msg = str(err)
    code = err.error_code or ""
    if "Network error" in msg or "timed out" in msg.lower():
        return "cannot_connect"
    if code in {"10000400", "70002057", "70002058", "10002057", "10002058"}:
        return "invalid_auth"
    if "captcha" in msg.lower() or code in {"70002082"}:
        return "captcha_required"
    if "sms" in msg.lower() or code in {"10000402", "10000201", "10001013"}:
        return "invalid_sms"
    return "invalid_auth"


class HonorRobotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 2

    def __init__(self) -> None:
        self._client: GritApiClient | None = None
        self._session: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []
        self._auth_mode = AUTH_MODE_PASSWORD
        self._name = DEFAULT_NAME
        self._honor: HonorIdClient | None = None
        self._honor_account = ""
        self._honor_password = ""
        self._honor_calling_code = DEFAULT_CALLING_CODE
        self._honor_language = DEFAULT_LANGUAGE
        self._honor_device_id = ""
        self._honor_sub_type = DEFAULT_SUB_TYPE
        self._captcha_trans_no = ""
        self._captcha_validate = ""
        self._verify_user_account = ""
        self._verify_account_type: str = "2"
        self._captcha_url = ""
        self._honor_session: dict = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HonorRobotOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["honor", "login", "token"],
        )

    # ---- Honor AI Space (password + captcha + SMS) -------------------

    async def async_step_honor(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._honor_account = user_input[CONF_ACCOUNT].strip()
            self._honor_password = user_input[CONF_PASSWORD]
            self._honor_calling_code = user_input.get(
                CONF_CALLING_CODE, DEFAULT_CALLING_CODE
            )
            self._honor_language = user_input.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
            self._honor_device_id = (user_input.get(CONF_DEVICE_ID) or "").strip()
            self._honor_sub_type = (
                user_input.get(CONF_SUB_TYPE) or DEFAULT_SUB_TYPE
            ).strip()
            self._name = user_input.get(CONF_NAME) or DEFAULT_NAME
            try:
                lang = "ru-ru" if self._honor_language.startswith("ru") else "en-us"
                country = "ru" if self._honor_calling_code == "007" else "ru"
                self._honor = HonorIdClient(lang=lang, country_code=country)
                await asyncio.to_thread(self._honor.bootstrap)
                challenge = await asyncio.to_thread(
                    self._honor.prepare_captcha, "remoteLogin"
                )
                self._captcha_trans_no = challenge.captcha_trans_no
                if challenge.captcha_type in (-1,) and not challenge.captcha_id:
                    # No interactive captcha — proceed directly
                    self._captcha_validate = ""
                    return await self._async_honor_after_captcha()
                async_put_captcha_session(
                    self.hass,
                    self.flow_id,
                    {
                        "captcha_type": challenge.captcha_type,
                        "captcha_trans_no": challenge.captcha_trans_no,
                        "captcha_id": challenge.captcha_id,
                        "captcha_server": challenge.captcha_server,
                        "captcha_static_server": challenge.captcha_static_server,
                    },
                )
                path = f"/api/honor_robot_cleaner/captcha/{self.flow_id}"
                try:
                    base = get_url(self.hass, prefer_external=True)
                    self._captcha_url = f"{base.rstrip('/')}{path}"
                except Exception:  # noqa: BLE001
                    self._captcha_url = path
                return await self.async_step_honor_captcha()
            except HonorIdError as err:
                _LOGGER.warning("Honor bootstrap/captcha failed: %s", err)
                errors["base"] = _classify_honor_error(err)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Honor setup failed")
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNT): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD
                    )
                ),
                vol.Required(CONF_DEVICE_ID): str,
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
                vol.Optional(CONF_SUB_TYPE, default=DEFAULT_SUB_TYPE): str,
                vol.Optional(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="honor", data_schema=schema, errors=errors
        )

    async def async_step_honor_captcha(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            validate = async_get_captcha_validate(self.hass, self.flow_id)
            if not validate:
                errors["base"] = "captcha_required"
            else:
                self._captcha_validate = validate
                return await self._async_honor_after_captcha()

        return self.async_show_form(
            step_id="honor_captcha",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"captcha_url": self._captcha_url},
        )

    async def _async_honor_after_captcha(self) -> FlowResult:
        assert self._honor is not None
        try:
            resp = await asyncio.to_thread(
                self._honor.login_password,
                self._honor_account,
                self._honor_password,
                captcha_validate=self._captcha_validate or None,
                captcha_trans_no=self._captcha_trans_no or None,
            )
            ok = str(resp.get("isSuccess")) in ("1", "true", "True")
            if ok and resp.get("callbackURL"):
                return await self._async_honor_finish(resp)

            if self._honor.needs_sms_verification(resp) or _looks_like_sms_gate(resp):
                targets = self._honor.parse_verify_targets(resp)
                if targets:
                    t0 = targets[0]
                    self._verify_user_account = str(
                        t0.get("userAccount")
                        or t0.get("name")
                        or t0.get("account")
                        or self._honor_account
                    )
                    self._verify_account_type = str(
                        t0.get("accountType") or t0.get("authAccountType") or "2"
                    )
                else:
                    self._verify_user_account = self._honor_account
                    self._verify_account_type = "2"
                sms_resp = await asyncio.to_thread(
                    self._honor.request_sms_code,
                    self._verify_user_account or self._honor_account,
                    calling_code=self._honor_calling_code,
                    captcha_validate=self._captcha_validate or None,
                    captcha_trans_no=self._captcha_trans_no or None,
                )
                if str(sms_resp.get("isSuccess")) not in ("1", "true", "True"):
                    _LOGGER.warning("getSMSAuthCode: %s", sms_resp)
                return await self.async_step_honor_sms()

            raise HonorIdError(
                resp.get("errorDesc") or "remoteLogin failed",
                error_code=str(resp.get("errorCode") or ""),
                data=resp,
            )
        except HonorIdError as err:
            _LOGGER.warning("Honor password login failed: %s", err)
            if err.error_code in {"70002082"} or "captcha" in str(err).lower():
                return self.async_show_form(
                    step_id="honor_captcha",
                    data_schema=vol.Schema({}),
                    errors={"base": "captcha_required"},
                    description_placeholders={"captcha_url": self._captcha_url},
                )
            if self._honor and self._honor.needs_sms_verification(err.data):
                return await self.async_step_honor_sms()
            return self.async_show_form(
                step_id="honor",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_ACCOUNT, default=self._honor_account): str,
                        vol.Required(CONF_PASSWORD): selector.TextSelector(
                            selector.TextSelectorConfig(
                                type=selector.TextSelectorType.PASSWORD
                            )
                        ),
                        vol.Required(
                            CONF_DEVICE_ID, default=self._honor_device_id
                        ): str,
                        vol.Required(
                            CONF_CALLING_CODE, default=self._honor_calling_code
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value=k, label=f"{v} [{k}]"
                                    )
                                    for k, v in CALLING_CODES.items()
                                ],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Optional(
                            CONF_SUB_TYPE, default=self._honor_sub_type
                        ): str,
                        vol.Optional(
                            CONF_LANGUAGE, default=self._honor_language
                        ): str,
                        vol.Optional(CONF_NAME, default=self._name): str,
                    }
                ),
                errors={"base": _classify_honor_error(err)},
            )

    async def async_step_honor_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._honor is not None
            code = (user_input.get(CONF_SMS_CODE) or "").strip()
            try:
                # Prefer password + two-step SMS (what AI Space asks for)
                resp = await asyncio.to_thread(
                    self._honor.login_password,
                    self._honor_account,
                    self._honor_password,
                    captcha_validate=self._captcha_validate or None,
                    captcha_trans_no=self._captcha_trans_no or None,
                    two_step_verify_code=code,
                    verify_user_account=self._verify_user_account
                    or self._honor_account,
                    verify_account_type=self._verify_account_type,
                    op_type=6,
                )
                if str(resp.get("isSuccess")) not in ("1", "true", "True"):
                    # Fallback: SMS-only login
                    resp = await asyncio.to_thread(
                        self._honor.login_sms,
                        self._honor_account,
                        code,
                        calling_code=self._honor_calling_code,
                        captcha_validate=self._captcha_validate or None,
                        captcha_trans_no=self._captcha_trans_no or None,
                    )
                if str(resp.get("isSuccess")) not in ("1", "true", "True"):
                    raise HonorIdError(
                        resp.get("errorDesc") or "SMS login failed",
                        error_code=str(resp.get("errorCode") or ""),
                        data=resp,
                    )
                return await self._async_honor_finish(resp)
            except HonorIdError as err:
                _LOGGER.warning("Honor SMS step failed: %s", err)
                errors["base"] = _classify_honor_error(err)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Honor SMS step failed")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="honor_sms",
            data_schema=vol.Schema({vol.Required(CONF_SMS_CODE): str}),
            errors=errors,
        )

    async def _async_honor_finish(self, login_resp: dict[str, Any]) -> FlowResult:
        assert self._honor is not None
        try:
            result = await asyncio.to_thread(
                self._honor.extract_auth_code, login_resp
            )
            client = GritApiClient(
                device_id=self._honor_device_id,
                sub_type=self._honor_sub_type,
                calling_code=self._honor_calling_code,
                language=self._honor_language,
                base_url=base_url_for_calling_code(self._honor_calling_code),
            )
            session = await client.async_login_honor_auth_code(
                result.auth_code,
                device_id=self._honor_device_id,
                sub_type=self._honor_sub_type,
                calling_code=self._honor_calling_code,
                language=self._honor_language,
            )
            # Persist Honor SSO cookies for autonomous Grit JWT refresh
            self._honor_session = await asyncio.to_thread(
                self._honor.export_session
            )
            client.honor_session = dict(self._honor_session)
            devices = await client.async_list_devices()
            if self._honor_device_id:
                match = [
                    d
                    for d in devices
                    if d.get("thing_name") == self._honor_device_id
                ]
                if not match:
                    match = [
                        {
                            "thing_name": self._honor_device_id,
                            "sub_type": self._honor_sub_type,
                            "thing_nickname": self._name,
                        }
                    ]
                devices = match
            if not devices:
                return self.async_abort(reason="no_devices")
            self._client = client
            self._session = {
                **session,
                CONF_ACCOUNT: self._honor_account,
                CONF_PASSWORD: self._honor_password,
                CONF_AUTH_MODE: AUTH_MODE_HONOR,
            }
            self._devices = devices
            self._auth_mode = AUTH_MODE_HONOR
            async_pop_captcha_session(self.hass, self.flow_id)
            if len(devices) == 1:
                return await self._async_create_from_device(devices[0])
            return await self.async_step_device()
        except (HonorIdError, GritApiError) as err:
            _LOGGER.warning("Honor finish failed: %s", err)
            if isinstance(err, GritApiError):
                err_key = _classify_grit_error(err)
            else:
                err_key = _classify_honor_error(err)
            return self.async_show_form(
                step_id="honor_sms",
                data_schema=vol.Schema({vol.Required(CONF_SMS_CODE): str}),
                errors={"base": err_key},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Honor finish failed")
            return self.async_show_form(
                step_id="honor_sms",
                data_schema=vol.Schema({vol.Required(CONF_SMS_CODE): str}),
                errors={"base": "unknown"},
            )

    # ---- Grit password -----------------------------------------------

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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
                errors["base"] = _classify_grit_error(err)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Login failed")
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNT): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD
                    )
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
        return self.async_show_form(
            step_id="login", data_schema=schema, errors=errors
        )

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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
                    auth_mode=AUTH_MODE_TOKEN,
                )
                devices = await client.async_list_devices()
                if parsed.get(CONF_DEVICE_ID):
                    match = [
                        d
                        for d in devices
                        if d.get("thing_name") == parsed[CONF_DEVICE_ID]
                    ]
                    if not match and devices:
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
                errors["base"] = _classify_grit_error(err)
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
        return self.async_show_form(
            step_id="token", data_schema=schema, errors=errors
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        options = {
            d["thing_name"]: _device_label(d)
            for d in self._devices
            if d.get("thing_name")
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

        title = device.get("thing_nickname") or self._name or DEFAULT_NAME
        data = {
            CONF_TOKEN: self._client.token,
            CONF_DEVICE_ID: device_id,
            CONF_REGION: self._client.region,
            CONF_BASE_URL: self._client.base_url,
            CONF_SUB_TYPE: sub_type,
            CONF_NAME: title,
            CONF_AUTH_MODE: self._auth_mode,
            CONF_TOKEN_EXPIRES_AT: self._client.token_expires_at
            or jwt_expires_at(self._client.token),
            CONF_HONOR_SESSION: self._honor_session
            or getattr(self._client, "honor_session", {})
            or {},
        }
        if self._auth_mode in (AUTH_MODE_PASSWORD, AUTH_MODE_HONOR):
            data.update(
                {
                    CONF_ACCOUNT: self._session.get(CONF_ACCOUNT)
                    or self._client.account,
                    CONF_PASSWORD: self._session.get(CONF_PASSWORD, ""),
                    CONF_CALLING_CODE: self._client.calling_code,
                    CONF_LANGUAGE: self._client.language,
                }
            )
        return self.async_create_entry(title=title, data=data)


class HonorRobotOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Update credentials / re-login / auto-refresh settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        current = {**self.config_entry.data, **self.options}
        mode = current.get(CONF_AUTH_MODE)
        if mode == AUTH_MODE_PASSWORD or (
            current.get(CONF_ACCOUNT) and mode != AUTH_MODE_HONOR
        ):
            return await self.async_step_password()
        return await self.async_step_refresh()

    async def async_step_refresh(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update token / trigger Honor silent refresh for Honor/token modes."""
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.options}
        if user_input is not None:
            try:
                token_raw = (user_input.get(CONF_TOKEN) or "").strip()
                data = {
                    CONF_DEVICE_ID: current.get(CONF_DEVICE_ID, ""),
                    CONF_REGION: current.get(CONF_REGION, DEFAULT_REGION),
                    CONF_BASE_URL: current.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                    CONF_SUB_TYPE: current.get(CONF_SUB_TYPE, DEFAULT_SUB_TYPE),
                    CONF_AUTH_MODE: current.get(CONF_AUTH_MODE, AUTH_MODE_TOKEN),
                    CONF_TOKEN: current.get(CONF_TOKEN, ""),
                    CONF_TOKEN_EXPIRES_AT: current.get(CONF_TOKEN_EXPIRES_AT),
                    CONF_ACCOUNT: current.get(CONF_ACCOUNT, ""),
                    CONF_PASSWORD: current.get(CONF_PASSWORD, ""),
                    CONF_CALLING_CODE: current.get(
                        CONF_CALLING_CODE, DEFAULT_CALLING_CODE
                    ),
                    CONF_LANGUAGE: current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    CONF_HONOR_SESSION: current.get(CONF_HONOR_SESSION) or {},
                }
                client = GritApiClient(
                    token=data[CONF_TOKEN],
                    device_id=data[CONF_DEVICE_ID],
                    region=data[CONF_REGION],
                    base_url=data[CONF_BASE_URL],
                    sub_type=data[CONF_SUB_TYPE],
                    auth_mode=data[CONF_AUTH_MODE],
                    honor_session=data.get(CONF_HONOR_SESSION) or {},
                    account=data.get(CONF_ACCOUNT, ""),
                    password=data.get(CONF_PASSWORD, ""),
                    calling_code=data.get(CONF_CALLING_CODE, DEFAULT_CALLING_CODE),
                    language=data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    token_expires_at=data.get(CONF_TOKEN_EXPIRES_AT),
                )
                if token_raw:
                    merged = {**current, CONF_TOKEN: token_raw}
                    parsed = _normalize_token_credentials(merged)
                    client.token = parsed[CONF_TOKEN]
                    client.device_id = parsed[CONF_DEVICE_ID] or client.device_id
                    client.region = parsed[CONF_REGION]
                    client.base_url = parsed[CONF_BASE_URL]
                    client.sub_type = parsed[CONF_SUB_TYPE]
                    client.sync_token_expiry()
                elif client.honor_session:
                    await client.async_ensure_token(force=True)
                await client.async_get_status()
                data.update(
                    {
                        CONF_TOKEN: client.token,
                        CONF_DEVICE_ID: client.device_id,
                        CONF_REGION: client.region,
                        CONF_BASE_URL: client.base_url,
                        CONF_TOKEN_EXPIRES_AT: client.token_expires_at,
                        CONF_HONOR_SESSION: client.honor_session
                        or data.get(CONF_HONOR_SESSION)
                        or {},
                    }
                )
                return self.async_create_entry(title="", data=data)
            except ValueError:
                errors["base"] = "invalid_token_format"
            except GritApiError as err:
                _LOGGER.warning("Options refresh failed: %s", err)
                errors["base"] = _classify_grit_error(err)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Options refresh failed")
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TOKEN, default=current.get(CONF_TOKEN, "")
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD, multiline=True
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="refresh", data_schema=schema, errors=errors
        )

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
                        CONF_CALLING_CODE,
                        current.get(CONF_CALLING_CODE, DEFAULT_CALLING_CODE),
                    ),
                    language=user_input.get(
                        CONF_LANGUAGE,
                        current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    ),
                    auth_mode=AUTH_MODE_PASSWORD,
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
            except GritApiError as err:
                _LOGGER.warning("Options re-login failed: %s", err)
                errors["base"] = _classify_grit_error(err)
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
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD
                    )
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


def _looks_like_sms_gate(resp: dict[str, Any]) -> bool:
    """Extra heuristics when Honor asks for SMS after password."""
    code = str(resp.get("errorCode") or "")
    # Common “need second factor / risk / verify” families
    if code.startswith("70002") or code in {"11000400", "10002083", "70008800"}:
        desc = str(resp.get("errorDesc") or "").lower()
        if any(
            x in desc
            for x in ("sms", "verify", "authcode", "risk", "factor", "phone")
        ):
            return True
    return bool(resp.get("isDoubleVerification"))


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
