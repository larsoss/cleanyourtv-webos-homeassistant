"""The TV as a media player, both ways: the TV reports the app in front, whether it plays or is paused, the Live TV channel with its
programme and logo, and the volume; Home Assistant turns it on (Wake-on-LAN) and off, sets the volume, plays, pauses and picks a source."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SIGNAL_LISTS, CytvConfigEntry
from .client import CytvError
from .const import CONF_LIVE_SOURCES, CONF_MAC, DOMAIN, HOME_APP, LIVE_PREFIX, MEDIA_TYPE_APP, MEDIA_TYPE_CHANNEL
from .entity import CytvEntity

LOGO = Path(__file__).parent / "brand" / "icon@2x.png"


def _read_logo() -> bytes:
    return LOGO.read_bytes()

F = MediaPlayerEntityFeature
LIVE_TV = "Live TV"


async def async_setup_entry(hass: HomeAssistant, entry: CytvConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([CytvMediaPlayer(entry)])


async def turn_on(entity: CytvEntity) -> None:
    """Turn the TV on: a dark screen comes back with turnOnScreen; a TV in standby gets Wake-on-LAN."""
    client = entity._client
    if client.connected and client.power_state == "Screen Off":
        try:
            await client.async_power("on")
            return
        except CytvError:
            pass
    # the packet is sent from a worker thread: the event loop does no socket work of its own
    if not await entity.hass.async_add_executor_job(client.wake, entity._entry.data.get(CONF_MAC)):
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_mac")


class CytvMediaPlayer(CytvEntity, MediaPlayerEntity):
    _attr_name = None  # the device's own name
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_media_image_remotely_accessible = False  # Home Assistant fetches the logo from the TV (it needs the token)
    _attr_supported_features = (
        F.TURN_ON | F.TURN_OFF | F.VOLUME_SET | F.VOLUME_STEP | F.VOLUME_MUTE | F.SELECT_SOURCE | F.PLAY | F.PAUSE | F.STOP
        | F.NEXT_TRACK | F.PREVIOUS_TRACK | F.PLAY_MEDIA
    )  # fmt: skip

    def __init__(self, entry: CytvConfigEntry) -> None:
        super().__init__(entry, "media_player")
        self._sources: dict[str, tuple[str, Any]] = {}
        self._titles: dict[str, str] = {}  # app id -> name, from the TV's lists
        self._no_icon: set[str] = set()  # apps the TV has no icon for

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_LISTS.format(self._entry.entry_id), self._lists_changed))
        self._build_sources()

    @callback
    def _lists_changed(self) -> None:
        self._build_sources()
        self.async_write_ha_state()

    def _build_sources(self) -> None:
        """Inputs first (HDMI, the tuner), then the apps, then (if chosen in the options) the Live TV channels."""
        src: dict[str, tuple[str, Any]] = {}
        titles: dict[str, str] = {}
        for i in self._data.inputs:
            name = i.get("title") or i["appId"]
            src.setdefault(name, ("app", i["appId"]))
            titles[i["appId"]] = name
        for a in sorted(self._data.apps, key=lambda a: a["title"].lower()):
            src.setdefault(a["title"], ("app", a["id"]))
            titles.setdefault(a["id"], a["title"])
        if self._entry.options.get(CONF_LIVE_SOURCES):
            for c in self._data.channels:
                src.setdefault(f"{LIVE_PREFIX}{c['num']} {c.get('name', '')}".strip(), ("live", c["num"]))
        self._sources = src
        self._titles = titles

    # ---- what the TV reports ----
    @property
    def state(self) -> MediaPlayerState:
        if not self.tv_on:
            return MediaPlayerState.OFF
        if self._client.power_state in ("Screen Off", "Screen Saver"):
            return MediaPlayerState.IDLE
        play = self._client.media.get("state")
        if play == "playing":
            return MediaPlayerState.PLAYING
        if play == "paused":
            return MediaPlayerState.PAUSED
        if play in ("loaded", "buffering"):
            return MediaPlayerState.BUFFERING
        return MediaPlayerState.ON

    @property
    def _live(self) -> dict[str, Any] | None:
        return self._client.live if self.tv_on else None

    @property
    def app_id(self) -> str | None:
        return self._client.app or None if self.tv_on else None

    @property
    def app_name(self) -> str | None:
        if not self.app_id:
            return None
        if self._live or (self.app_id == HOME_APP and self._client.media.get("appId") == HOME_APP):
            return LIVE_TV
        if self.app_id == HOME_APP:
            return "Home"
        return self._titles.get(self.app_id, self.app_id)

    @property
    def source(self) -> str | None:
        live = self._live
        if live and self._entry.options.get(CONF_LIVE_SOURCES):
            name = f"{LIVE_PREFIX}{live['num']} {live.get('name', '')}".strip()
            if name in self._sources:
                return name
        return self._titles.get(self.app_id) if self.app_id else None

    @property
    def source_list(self) -> list[str]:
        return list(self._sources)

    @property
    def media_content_type(self) -> str | None:
        if self._live:
            return MediaType.CHANNEL
        return MediaType.APP if self.app_id else None

    @property
    def media_content_id(self) -> str | None:
        live = self._live
        if live:
            return str(live["num"])
        return self.app_id

    @property
    def media_channel(self) -> str | None:
        live = self._live
        return f"{live['num']} {live.get('name', '')}".strip() if live else None

    @property
    def media_title(self) -> str | None:
        live = self._live
        if live:
            prog = live.get("programme") or {}
            return prog.get("title") or live.get("name")
        return self.app_name

    @property
    def media_series_title(self) -> str | None:
        live = self._live
        return live.get("name") if live and (live.get("programme") or {}).get("title") else None

    @property
    def media_duration(self) -> int | None:
        prog = (self._live or {}).get("programme") or {}
        if prog.get("start") and prog.get("end"):
            return int(prog["end"]) - int(prog["start"])
        return None

    @property
    def media_position(self) -> int | None:
        prog = (self._live or {}).get("programme") or {}
        if prog.get("start") and prog.get("end"):
            return max(0, int(datetime.now(UTC).timestamp()) - int(prog["start"]))
        return None

    @property
    def media_position_updated_at(self) -> datetime | None:
        return datetime.now(UTC) if self.media_position is not None else None

    @property
    def media_image_hash(self) -> str | None:
        live = self._live
        if live and live.get("logo"):
            return f"logo{live['num']}"
        if self.app_id == HOME_APP:
            return "cleanyourtv"  # Home is CleanYourTV's: its own logo (the TV has no icon for it)
        if self.app_id and not live and self.app_id not in self._no_icon:
            return f"icon{self.app_id}"
        return None

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        live = self._live
        if live and live.get("logo"):
            return await self._client.async_picture(f"/api/logo/{int(live['num'])}")
        if self.app_id == HOME_APP:
            return await self.hass.async_add_executor_job(_read_logo), "image/png"
        if self.app_id:
            app = self.app_id
            body, ctype = await self._client.async_picture(f"/api/icon/{app}")
            if body is None and app not in self._no_icon:
                # no icon for this app: no picture at all, rather than a broken one
                self._no_icon.add(app)
                self.async_write_ha_state()
            return body, ctype
        return None, None

    @property
    def volume_level(self) -> float | None:
        v = self._client.volume if self.tv_on else None
        if not v or v.get("level") is None:
            return None
        return max(0.0, min(1.0, float(v["level"]) / float(v.get("max") or 100)))

    @property
    def is_volume_muted(self) -> bool | None:
        v = self._client.volume if self.tv_on else None
        return bool(v["mute"]) if v and v.get("mute") is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        out: dict[str, Any] = {"connected": self._client.connected}
        if self._client.power_state:
            out["power_state"] = self._client.power_state
        live = self._live
        if live:
            out["live_channel_number"] = live["num"]
            out["live_channel_name"] = live.get("name")
            out["live_channel_group"] = live.get("group")
            prog = live.get("programme") or {}
            if prog.get("title"):
                out["programme_title"] = prog["title"]
                out["programme_start"] = datetime.fromtimestamp(int(prog["start"]), UTC).isoformat()
                out["programme_end"] = datetime.fromtimestamp(int(prog["end"]), UTC).isoformat()
                if prog.get("description"):
                    out["programme_description"] = prog["description"]
            nxt = live.get("next") or {}
            if nxt.get("title"):
                out["next_programme_title"] = nxt["title"]
                out["next_programme_start"] = datetime.fromtimestamp(int(nxt["start"]), UTC).isoformat()
        v = self._client.volume if self.tv_on else None
        if v and v.get("output"):
            out["sound_output"] = v["output"]
        return out

    # ---- control ----
    async def _do(self, coro) -> None:
        try:
            await coro
        except CytvError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_on(self) -> None:
        await turn_on(self)

    async def async_turn_off(self) -> None:
        await self._do(self._client.async_power("standby"))

    async def async_set_volume_level(self, volume: float) -> None:
        v = self._client.volume or {}
        await self._do(self._client.async_set_volume(round(volume * float(v.get("max") or 100))))

    async def async_volume_up(self) -> None:
        await self._do(self._client.async_key("VOLUMEUP"))

    async def async_volume_down(self) -> None:
        await self._do(self._client.async_key("VOLUMEDOWN"))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._do(self._client.async_set_mute(mute))

    async def async_media_play(self) -> None:
        await self._do(self._client.async_key("PLAY"))

    async def async_media_pause(self) -> None:
        await self._do(self._client.async_key("PAUSE"))

    async def async_media_stop(self) -> None:
        await self._do(self._client.async_key("STOP"))

    async def async_media_next_track(self) -> None:
        await self._do(self._client.async_key("CHANNELUP"))

    async def async_media_previous_track(self) -> None:
        await self._do(self._client.async_key("CHANNELDOWN"))

    async def async_select_source(self, source: str) -> None:
        hit = self._sources.get(source)
        if hit is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="unknown_source", translation_placeholders={"source": source}
            )
        kind, value = hit
        await self._do(self._client.async_live(value) if kind == "live" else self._client.async_launch(value))

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        if media_type == MEDIA_TYPE_APP:
            await self._do(self._client.async_launch(media_id))
        elif media_type == MEDIA_TYPE_CHANNEL:
            try:
                num = int(media_id)
            except ValueError as err:
                raise ServiceValidationError(f"not a channel number: {media_id}") from err
            await self._do(self._client.async_live(num))
        else:
            raise ServiceValidationError(f"media type {media_type} is not supported: use app or channel")
