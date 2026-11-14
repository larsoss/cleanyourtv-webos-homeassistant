"""The remote control: every key of the TV remote, and the actions for text, apps, channels, power and the pointer.

remote.send_command takes key names (UP, ENTER, HOME, VOLUMEUP, RED, 1, ...) and a few words of its own:
  text:<text>   types into the text field open on the TV      enter / delete / click
  launch:<id>   opens an app (com.webos.app.hdmi1, netflix)  live:<number>  Live TV on that channel
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

import voluptuous as vol
from homeassistant.components.remote import ATTR_DELAY_SECS, ATTR_NUM_REPEATS, DEFAULT_DELAY_SECS, RemoteEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CytvConfigEntry, refresh_lists
from .client import KEYS, NOTIFY_PICTURE_MAX, POWER_ACTIONS, CytvError
from .const import CONF_JF_APP, CONF_JF_KEY, CONF_JF_URL, CONF_JF_USER, DEFAULT_JF_APP, DOMAIN, JF_CLIENTS, PLAY_WAIT_S
from .entity import CytvEntity
from .media_player import turn_on

_LOGGER = logging.getLogger(__name__)

POSITIONS = [f"{v}-{h}" for v in ("top", "middle", "bottom") for h in ("left", "center", "right")]


async def async_setup_entry(hass: HomeAssistant, entry: CytvConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([CytvTVEntity(entry)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "send_text", {vol.Required("text"): cv.string, vol.Optional("enter", default=False): cv.boolean}, "async_send_text"
    )
    platform.async_register_entity_service("launch_app", {vol.Required("app_id"): vol.Match(r"^[\w.\-]+$")}, "async_launch_app")
    platform.async_register_entity_service(
        "live_channel", {vol.Required("channel"): vol.All(vol.Coerce(int), vol.Range(1, 99999))}, "async_live_channel"
    )
    platform.async_register_entity_service("tv_power", {vol.Required("action"): vol.In(POWER_ACTIONS)}, "async_tv_power")
    platform.async_register_entity_service(
        "pointer",
        {
            vol.Optional("dx", default=0): vol.All(vol.Coerce(int), vol.Range(-500, 500)),
            vol.Optional("dy", default=0): vol.All(vol.Coerce(int), vol.Range(-500, 500)),
            vol.Optional("click", default=False): cv.boolean,
            vol.Optional("scroll", default=0): vol.All(vol.Coerce(int), vol.Range(-50, 50)),
        },
        "async_pointer",
    )
    platform.async_register_entity_service("refresh_lists", None, "async_refresh_lists")
    platform.async_register_entity_service(
        "show_notification",
        {
            vol.Optional("title", default=""): vol.All(cv.string, vol.Length(max=120)),
            vol.Optional("message", default=""): vol.All(cv.string, vol.Length(max=400)),
            vol.Optional("camera"): cv.entity_domain("camera"),
            vol.Optional("image_url"): cv.string,
            vol.Optional("seconds", default=10): vol.All(vol.Coerce(int), vol.Range(2, 120)),
            vol.Optional("position", default="top-right"): vol.In(POSITIONS),
        },
        "async_show_notification",
    )
    platform.async_register_entity_service(
        "play",
        {
            vol.Required("title"): vol.All(cv.string, vol.Length(min=1, max=120)),
            vol.Optional("season"): vol.All(vol.Coerce(int), vol.Range(0, 99)),
            vol.Optional("episode"): vol.All(vol.Coerce(int), vol.Range(0, 999)),
            vol.Optional("resume", default=True): cv.boolean,
        },
        "async_play_title",
    )


class CytvTVEntity(CytvEntity, RemoteEntity):
    _attr_translation_key = "remote"
    _unrecorded_attributes = frozenset({"keys", "apps", "inputs"})

    def __init__(self, entry: CytvConfigEntry) -> None:
        super().__init__(entry, "remote")

    @property
    def is_on(self) -> bool:
        return self.tv_on

    async def _do(self, coro) -> None:
        try:
            await coro
        except CytvError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await turn_on(self)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._do(self._client.async_power("standby"))

    def _command(self, cmd: str):
        c = str(cmd).strip()
        word, _, arg = c.partition(":")
        w = word.strip().lower()
        if arg and w == "text":
            return self._client.async_text(arg)
        if arg and w == "launch":
            return self._client.async_launch(arg.strip())
        if arg and w == "live":
            if not arg.strip().isdigit():
                raise ServiceValidationError(f"not a channel number: {arg}")
            return self._client.async_live(int(arg))
        if not arg and w == "enter":
            return self._client.async_enter()
        if not arg and w == "delete":
            return self._client.async_delete(1)
        if not arg and w == "click":
            return self._client.async_click()
        if c.upper() in KEYS:
            return self._client.async_key(c.upper())
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_command", translation_placeholders={"command": c})

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        repeats = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        cmds = list(command)
        for c in cmds:  # every word is checked before the first one is sent
            self._command(c).close()
        first = True
        for _ in range(repeats):
            for c in cmds:
                if not first and delay:
                    await asyncio.sleep(delay)
                first = False
                await self._do(self._command(c))

    async def async_send_text(self, text: str, enter: bool = False) -> None:
        await self._do(self._client.async_text(text))
        if enter:
            await self._do(self._client.async_enter())

    async def async_launch_app(self, app_id: str) -> None:
        await self._do(self._client.async_launch(app_id))

    async def async_live_channel(self, channel: int) -> None:
        await self._do(self._client.async_live(channel))

    async def async_tv_power(self, action: str) -> None:
        await self._do(self._client.async_power(action))

    async def async_pointer(self, dx: int = 0, dy: int = 0, click: bool = False, scroll: int = 0) -> None:
        if dx or dy:
            await self._do(self._client.async_move(dx, dy))
        if click:
            await self._do(self._client.async_click())
        if scroll:
            await self._do(self._client.async_scroll(scroll))

    async def async_show_notification(
        self,
        title: str = "",
        message: str = "",
        camera: str | None = None,
        image_url: str | None = None,
        seconds: int = 10,
        position: str = "top-right",
    ) -> None:
        """A card over whatever is on the TV: a title, a text and a picture. Home Assistant gets the picture (a camera's snapshot, or
        an address Home Assistant can reach) and sends it along, so the TV needs no way to Home Assistant."""
        image: bytes | None = None
        image_type = "image/jpeg"
        if camera:
            from homeassistant.components.camera import async_get_image

            try:
                img = await async_get_image(self.hass, camera, timeout=10)
            except HomeAssistantError as err:
                raise HomeAssistantError(f"no picture from {camera}: {err}") from err
            image, image_type = img.content, img.content_type
        elif image_url:
            image, image_type = await self._fetch_picture(image_url)
        if not (title or message or image):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="nothing_to_show")
        if image and len(image) > NOTIFY_PICTURE_MAX:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="picture_too_large")
        await self._do(self._client.async_notify(title, message, seconds, position, image, image_type))

    async def async_play_title(self, title: str, season: int | None = None, episode: int | None = None, resume: bool = True) -> None:
        """Put a series or film on: find it on the Jellyfin server, open the app on the TV and play it there."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        from .jellyfin import Jellyfin, JellyfinAuthError, JellyfinError, resume_ticks

        o = self._entry.options
        if not (o.get(CONF_JF_URL) and o.get(CONF_JF_KEY)):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_jellyfin")
        jf = Jellyfin(async_get_clientsession(self.hass), o[CONF_JF_URL], o[CONF_JF_KEY], o.get(CONF_JF_USER, ""))
        try:
            item = await self._find(jf, title, season, episode)
            ticks = resume_ticks(item) if resume else 0
            session = await self._tv_session(jf, self._play_app(o.get(CONF_JF_APP) or DEFAULT_JF_APP))
            await jf.async_play(session["Id"], item["Id"], ticks)
        except JellyfinAuthError as err:
            raise HomeAssistantError(str(err)) from err
        except JellyfinError as err:
            raise HomeAssistantError(str(err)) from err

    async def _find(self, jf: Any, title: str, season: int | None, episode: int | None) -> dict[str, Any]:
        """The film, or the episode of the series: the one asked for, else the one to watch next."""
        found = await jf.async_search(title)
        if not found:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_found", translation_placeholders={"title": title})
        item = found[0]
        if item.get("Type") != "Series":
            return item
        name = str(item.get("Name") or title)
        got = (
            await jf.async_episode(item["Id"], season, episode)
            if season is not None or episode is not None
            else await jf.async_next_up(item["Id"])
        )
        if not got:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_episode", translation_placeholders={"title": name})
        return got

    def _play_app(self, app: str) -> str:
        """The Jellyfin client to open: the chosen one, or another one that is on the TV when the chosen one is not installed."""
        ids = {a["id"] for a in self._data.apps if a.get("id")}
        if not ids or app in ids:  # an empty list means the TV has not been read yet: just use what was chosen
            return app
        other = next((i for i in JF_CLIENTS if i in ids), "")
        if not other:
            return app
        _LOGGER.info("%s is not installed on the TV, opening %s (%s) instead", app, JF_CLIENTS[other], other)
        return other

    async def _tv_session(self, jf: Any, app: str) -> dict[str, Any]:
        """The Jellyfin app on the TV, opened first when it is not in front: a session takes a moment to sign in."""
        model, host = self._client.model or "", self._entry.data.get(CONF_HOST, "")
        session = jf.tv_session(await jf.async_sessions(), model, host)
        if session:
            return session
        await self._do(self._client.async_action("launch", id=app))
        end = self.hass.loop.time() + PLAY_WAIT_S
        while self.hass.loop.time() < end:
            await asyncio.sleep(2)
            session = jf.tv_session(await jf.async_sessions(), model, host)
            if session:
                return session
        raise HomeAssistantError(
            f"{app} was opened on the TV but did not sign in to the Jellyfin server within {PLAY_WAIT_S} seconds; "
            "the app has to be signed in to the same server, and has to be a client the server can play on"
        )

    async def _fetch_picture(self, url: str) -> tuple[bytes, str]:
        """A picture from an address: one of Home Assistant itself (/api/..., /local/...) or of the network."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        from homeassistant.helpers.network import NoURLAvailableError, get_url

        if url.startswith("/"):
            try:
                url = get_url(self.hass, allow_external=False) + url
            except NoURLAvailableError as err:
                raise HomeAssistantError("Home Assistant does not know its own address for this picture") from err
        try:
            async with asyncio.timeout(15):
                async with async_get_clientsession(self.hass).get(url) as resp:
                    if resp.status != 200:
                        raise HomeAssistantError(f"the picture's address answered {resp.status}")
                    ctype = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                    if not ctype.startswith("image/"):
                        raise HomeAssistantError("that address is not a picture")
                    body = await resp.content.read(NOTIFY_PICTURE_MAX + 1)
        except (TimeoutError, OSError, ValueError) as err:
            raise HomeAssistantError(f"could not get the picture: {err}") from err
        return body, ctype

    async def async_refresh_lists(self) -> None:
        refresh_lists(self.hass, self._entry)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "keys": KEYS,
            "apps": {a["title"]: a["id"] for a in self._data.apps},
            "inputs": {i.get("title") or i["appId"]: i["appId"] for i in self._data.inputs},
            "channels": len(self._data.channels),
        }
