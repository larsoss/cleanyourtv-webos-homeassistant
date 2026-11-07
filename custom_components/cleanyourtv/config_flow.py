"""Pairing Home Assistant with the TV: the address of the TV and the 6-digit code the add-on's page shows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import DEFAULT_PORT, CytvError, CytvPairError, CytvTV, async_pair
from .const import CONF_CODE, CONF_DEVICE_NAME, CONF_LIVE_SOURCES, CONF_MAC, CONF_TOKEN, DEFAULT_DEVICE_NAME, DOMAIN


class CytvConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._host = ""
        self._port = DEFAULT_PORT
        self._name = DEFAULT_DEVICE_NAME

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return CytvOptionsFlow()

    async def _pair(self, code: str, errors: dict[str, str], placeholders: dict[str, str]) -> tuple[str, dict[str, Any]] | None:
        """Pair and connect once; returns (token, the TV's ready message) or fills errors."""
        session = async_get_clientsession(self.hass)
        try:
            token, _name = await async_pair(session, self._host, self._port, code, self._name)
            ready = await CytvTV(session, self._host, self._port, token).async_get_state(0, timeout=10)
        except CytvPairError as err:
            errors["base"] = err.reason if err.reason in ("not_waiting", "wrong_code", "too_many_tries", "too_many_devices") else "unknown"
            placeholders["message"] = str(err)
            return None
        except CytvError:
            errors["base"] = "cannot_connect"
            return None
        return token, ready

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            self._port = user_input[CONF_PORT]
            self._name = user_input[CONF_DEVICE_NAME].strip() or DEFAULT_DEVICE_NAME
            self._async_abort_entries_match({CONF_HOST: self._host})
            got = await self._pair(user_input[CONF_CODE], errors, placeholders)
            if got:
                token, ready = got
                tv = ready.get("tv") or {}
                mac = str(tv.get("mac") or "")
                if mac:
                    await self.async_set_unique_id(dr.format_mac(mac))
                    self._abort_if_unique_id_configured(updates={CONF_HOST: self._host, CONF_PORT: self._port, CONF_TOKEN: token})
                return self.async_create_entry(
                    title=str(tv.get("model") or self._host),
                    data={CONF_HOST: self._host, CONF_PORT: self._port, CONF_TOKEN: token, CONF_MAC: mac},
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._host): str,
                vol.Required(CONF_CODE): str,
                vol.Required(CONF_DEVICE_NAME, default=self._name): str,
                vol.Required(CONF_PORT, default=self._port): vol.All(vol.Coerce(int), vol.Range(1, 65535)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors, description_placeholders=placeholders)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._host = entry_data[CONF_HOST]
        self._port = entry_data.get(CONF_PORT, DEFAULT_PORT)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"message": "", "host": self._host}
        if user_input is not None:
            self._name = user_input[CONF_DEVICE_NAME].strip() or DEFAULT_DEVICE_NAME
            got = await self._pair(user_input[CONF_CODE], errors, placeholders)
            if got:
                token, ready = got
                entry = self._get_reauth_entry()
                tv = ready.get("tv") or {}
                mac = str(tv.get("mac") or "") or entry.data.get(CONF_MAC, "")
                return self.async_update_reload_and_abort(entry, data={**entry.data, CONF_TOKEN: token, CONF_MAC: mac})
        schema = vol.Schema({vol.Required(CONF_CODE): str, vol.Required(CONF_DEVICE_NAME, default=self._name): str})
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors, description_placeholders=placeholders)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """A new address for the TV (it got another IP): the pairing stays."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host, port = user_input[CONF_HOST].strip(), user_input[CONF_PORT]
            try:
                await CytvTV(async_get_clientsession(self.hass), host, port, entry.data[CONF_TOKEN]).async_get_state(0, timeout=10)
            except CytvError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data={**entry.data, CONF_HOST: host, CONF_PORT: port})
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                vol.Required(CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)): vol.All(vol.Coerce(int), vol.Range(1, 65535)),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)


class CytvOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema({vol.Required(CONF_LIVE_SOURCES, default=self.config_entry.options.get(CONF_LIVE_SOURCES, False)): bool})
        return self.async_show_form(step_id="init", data_schema=schema)
