"""Config flow for Honor Robot Cleaner."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import GritApiClient, GritApiError, parse_plugin_account_token
from .const import (
    CONF_BASE_URL,
    CONF_DEVICE_ID,
    CONF_NAME,
    CONF_REGION,
    CONF_SUB_TYPE,
    CONF_TOKEN,
    DEFAULT_BASE_URL,
    DEFAULT_NAME,
    DEFAULT_REGION,
    DEFAULT_SUB_TYPE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD, multiline=True)
        ),
        vol.Optional(CONF_DEVICE_ID): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Optional(CONF_REGION, default=DEFAULT_REGION): str,
        vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
        vol.Optional(CONF_SUB_TYPE, default=DEFAULT_SUB_TYPE): str,
    }
)


class HonorRobotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HonorRobotOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parsed = _normalize_credentials(user_input)
                client = GritApiClient(
                    token=parsed[CONF_TOKEN],
                    device_id=parsed[CONF_DEVICE_ID],
                    region=parsed[CONF_REGION],
                    base_url=parsed[CONF_BASE_URL],
                    sub_type=parsed[CONF_SUB_TYPE],
                )
                await client.async_get_status()
                await self.async_set_unique_id(parsed[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured()
                title = user_input.get(CONF_NAME) or DEFAULT_NAME
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_TOKEN: parsed[CONF_TOKEN],
                        CONF_DEVICE_ID: parsed[CONF_DEVICE_ID],
                        CONF_REGION: parsed[CONF_REGION],
                        CONF_BASE_URL: parsed[CONF_BASE_URL],
                        CONF_SUB_TYPE: parsed[CONF_SUB_TYPE],
                        CONF_NAME: title,
                    },
                )
            except ValueError:
                errors["base"] = "invalid_token_format"
            except GritApiError as err:
                _LOGGER.warning("API validation failed: %s", err)
                msg = str(err).lower()
                if "token" in msg:
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected validation error")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA,
            errors=errors,
        )


class HonorRobotOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Update token / connection options (token expires ~24h)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.options}

        if user_input is not None:
            try:
                merged = {**current, **user_input}
                parsed = _normalize_credentials(merged)
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
                    },
                )
            except ValueError:
                errors["base"] = "invalid_token_format"
            except GritApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Options validation failed")
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN, default=current.get(CONF_TOKEN, "")): selector.TextSelector(
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
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


def _normalize_credentials(user_input: dict[str, Any]) -> dict[str, str]:
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

    if not token or not device_id:
        raise ValueError("token and device_id required")

    if not base_url.endswith("/"):
        base_url += "/"

    return {
        CONF_TOKEN: token,
        CONF_DEVICE_ID: device_id,
        CONF_REGION: region,
        CONF_BASE_URL: base_url,
        CONF_SUB_TYPE: sub_type,
    }
