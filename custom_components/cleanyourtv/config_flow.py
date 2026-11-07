"""Finding and pairing the TV. Home Assistant finds LG TVs by their SSDP announcement (as LG's own webOS integration does) and asks each
one whether it runs the CleanYourTV add-on. Pairing works like a Hue bridge: choose "Pair Home Assistant" on the TV, then Submit here."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

from .client import DEFAULT_PORT, CytvError, CytvPairError, CytvTV, async_hello, async_pair
from .const import CONF_DEVICE_NAME, CONF_LIVE_SOURCES, CONF_MAC, CONF_TOKEN, DEFAULT_DEVICE_NAME, DOMAIN

PAIR_ERRORS = ("not_waiting", "too_many_tries", "too_many_devices")


class CytvConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._host = ""
        self._port = DEFAULT_PORT
        self._name = DEFAULT_DEVICE_NAME
        self._model = ""

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return CytvOptionsFlow()

    async def _pair(self, errors: dict[str, str], placeholders: dict[str, str]) -> tuple[str, dict[str, Any]] | None:
        """Pair and read the state once; returns (token, state) or fills errors."""
        session = async_get_clientsession(self.hass)
        try:
            await async_hello(session, self._host, self._port)
        except CytvError:
            errors["base"] = "cannot_connect"
            return None
        try:
            token, _name = await async_pair(session, self._host, self._port, self._name)
            state = await CytvTV(session, self._host, self._port, token).async_get_state(0, timeout=10)
        except CytvPairError as err:
            errors["base"] = err.reason if err.reason in PAIR_ERRORS else "unknown"
            placeholders["message"] = str(err)
            return None
        except CytvError:
            errors["base"] = "cannot_connect"
            return None
        return token, state

    def _create(self, token: str, state: dict[str, Any]) -> ConfigFlowResult:
        tv = state.get("tv") or {}
        return self.async_create_entry(
            title=str(tv.get("model") or self._model or self._host),
            data={CONF_HOST: self._host, CONF_PORT: self._port, CONF_TOKEN: token, CONF_MAC: str(tv.get("mac") or "")},
        )

    # ---- by hand: the address of the TV ----
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            self._port = user_input[CONF_PORT]
            self._name = user_input[CONF_DEVICE_NAME].strip() or DEFAULT_DEVICE_NAME
            self._async_abort_entries_match({CONF_HOST: self._host})
            got = await self._pair(errors, placeholders)
            if got:
                mac = str((got[1].get("tv") or {}).get("mac") or "")
                if mac:
                    await self.async_set_unique_id(dr.format_mac(mac))
                    self._abort_if_unique_id_configured(updates={CONF_HOST: self._host, CONF_PORT: self._port})
                return self._create(*got)
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._host): str,
                vol.Required(CONF_DEVICE_NAME, default=self._name): str,
                vol.Required(CONF_PORT, default=self._port): vol.All(vol.Coerce(int), vol.Range(1, 65535)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors, description_placeholders=placeholders)

    # ---- found on the network ----
    async def async_step_ssdp(self, discovery_info: SsdpServiceInfo) -> ConfigFlowResult:
        host = urlparse(discovery_info.ssdp_location or "").hostname
        if not host:
            return self.async_abort(reason="not_cleanyourtv")
        try:
            hello = await async_hello(async_get_clientsession(self.hass), host, DEFAULT_PORT)
        except CytvError:
            # an LG TV without the add-on (or without CleanYourTV): nothing to offer
            return self.async_abort(reason="not_cleanyourtv")
        mac = str(hello.get("mac") or "")
        if mac:
            await self.async_set_unique_id(dr.format_mac(mac))
            # a TV that is set up already and got a new address: the address is updated, nothing is asked
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._async_abort_entries_match({CONF_HOST: host})
        self._host, self._port = host, DEFAULT_PORT
        self._model = str(hello.get("model") or discovery_info.upnp.get("friendlyName") or host)
        self.context["title_placeholders"] = {"name": self._model}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"message": "", "name": self._model, "host": self._host}
        if user_input is not None:
            self._name = user_input[CONF_DEVICE_NAME].strip() or DEFAULT_DEVICE_NAME
            got = await self._pair(errors, placeholders)
            if got:
                return self._create(*got)
        schema = vol.Schema({vol.Required(CONF_DEVICE_NAME, default=self._name): str})
        return self.async_show_form(step_id="confirm", data_schema=schema, errors=errors, description_placeholders=placeholders)

    # ---- the TV forgot Home Assistant ----
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._host = entry_data[CONF_HOST]
        self._port = entry_data.get(CONF_PORT, DEFAULT_PORT)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"message": "", "host": self._host}
        if user_input is not None:
            self._name = user_input[CONF_DEVICE_NAME].strip() or DEFAULT_DEVICE_NAME
            got = await self._pair(errors, placeholders)
            if got:
                token, state = got
                entry = self._get_reauth_entry()
                mac = str((state.get("tv") or {}).get("mac") or "") or entry.data.get(CONF_MAC, "")
                return self.async_update_reload_and_abort(entry, data={**entry.data, CONF_TOKEN: token, CONF_MAC: mac})
        schema = vol.Schema({vol.Required(CONF_DEVICE_NAME, default=self._name): str})
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors, description_placeholders=placeholders)

    # ---- a new address ----
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
