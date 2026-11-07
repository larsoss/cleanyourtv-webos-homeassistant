"""Talks to the Home Assistant add-on of CleanYourTV on the TV (tv-addon/catalog/homeassistant in this repository).

The add-on listens on port 8801 of the TV while a Home Assistant is paired (or the pairing window is open):
  GET  /api/hello                     -> {service: 'cleanyourtv-homeassistant', version, open}: is the add-on there, would it pair now
  POST /api/pair {name}               -> {token, name}: while "Pair Home Assistant" is open on the TV (or "Pair without asking" is on)
  GET  /api/state?since=<seq>         -> waits until something changed, then the whole state (a long poll: the TV pushes)
  POST /api/action {t, ...}           -> {ok, error}
  GET  /api/apps | inputs | channels  -> the lists; /api/logo/<n> and /api/icon/<id> are pictures
  POST /api/unpair                    -> the token stops working
Every call but the pairing carries "Authorization: Bearer <token>".
This module has no Home Assistant imports, so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from collections.abc import Callable
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 8801
POLL_TIMEOUT_S = 40  # the add-on answers a long poll after 25 s at the latest
RETRY_S = (2, 5, 10, 20, 30)  # waits between attempts while the TV does not answer; the last one repeats
ACTION_TIMEOUT_S = 10

# the buttons the TV takes (the Phone remote's remotekeys.js KEYS)
KEYS = [
    "UP", "DOWN", "LEFT", "RIGHT", "ENTER", "BACK", "HOME", "MENU", "EXIT", "INFO", "POWER",
    "VOLUMEUP", "VOLUMEDOWN", "MUTE", "CHANNELUP", "CHANNELDOWN",
    "PLAY", "PAUSE", "STOP", "REWIND", "FASTFORWARD",
    "RED", "GREEN", "YELLOW", "BLUE",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
]  # fmt: skip
POWER_ACTIONS = ("off", "on", "standby", "reboot", "shutdown")
# what tvpower/getPowerState says in standby
STANDBY_STATES = ("Active Standby", "Suspend", "Power Off")


class CytvError(Exception):
    """The TV could not be reached or did not do what was asked."""


class CytvAuthError(CytvError):
    """The TV no longer accepts the token: Home Assistant was removed on the TV."""


class CytvPairError(CytvError):
    """Pairing was refused; reason: not_waiting, too_many_tries, too_many_devices or unknown."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


async def async_hello(session: aiohttp.ClientSession, host: str, port: int = DEFAULT_PORT) -> dict[str, Any]:
    """Whether the TV runs the add-on: {service, version, open}; raises CytvError when it does not answer as the add-on."""
    try:
        async with asyncio.timeout(5):
            async with session.get(f"http://{host}:{port}/api/hello") as resp:
                body = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
        raise CytvError(f"cannot reach {host}:{port}: {err}") from err
    if not isinstance(body, dict) or body.get("service") != "cleanyourtv-homeassistant":
        raise CytvError(f"{host}:{port} is not the CleanYourTV Home Assistant add-on")
    return body


async def async_pair(session: aiohttp.ClientSession, host: str, port: int, name: str) -> tuple[str, str]:
    """Pair while the TV waits ("Pair Home Assistant" on its page); returns (token, the name the TV keeps for this Home Assistant)."""
    try:
        async with asyncio.timeout(10):
            async with session.post(f"http://{host}:{port}/api/pair", json={"name": name}) as resp:
                status = resp.status
                body = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
        raise CytvError(f"cannot reach {host}:{port}: {err}") from err
    body = body if isinstance(body, dict) else {}
    if status == 200 and body.get("token"):
        return str(body["token"]), str(body.get("name") or name)
    msg = str(body.get("error") or f"HTTP {status}")
    if status == 429:
        raise CytvPairError("too_many_tries", msg)
    if status == 409:
        raise CytvPairError("too_many_devices", msg)
    if status == 403 and body.get("reason") == "not_waiting":
        raise CytvPairError("not_waiting", msg)
    raise CytvPairError("unknown", msg)


def magic_packet(mac: str) -> bytes:
    hexmac = mac.replace(":", "").replace("-", "").lower()
    if len(hexmac) != 12:
        raise ValueError(f"not a MAC address: {mac}")
    return bytes.fromhex("ff" * 6 + hexmac * 16)


def send_wol(mac: str, host: str | None = None) -> None:
    """Wake the TV: to its own address (what works on Wi-Fi, where a broadcast is often not passed on) and as a broadcast."""
    pkt = magic_packet(mac)
    targets = [("255.255.255.255", 9)]
    if host:
        targets.insert(0, (host, 9))
    for addr in targets:
        with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(pkt, addr)


class CytvTV:
    """One paired TV: follows its state with a long poll, and sends actions."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, token: str) -> None:
        self._session = session
        self.host = host
        self.port = port
        self._token = token
        self._task: asyncio.Task | None = None
        self._listeners: list[Callable[[], None]] = []
        self._first = asyncio.Event()
        self.connected = False
        self.auth_failed = False
        self.state: dict[str, Any] = {}

    # ---- the state ----
    @property
    def power_state(self) -> str:
        return str(self.state.get("power") or "") if self.connected else ""

    @property
    def app(self) -> str:
        return str(self.state.get("app") or "")

    @property
    def media(self) -> dict[str, str]:
        return self.state.get("media") or {}

    @property
    def volume(self) -> dict[str, Any] | None:
        return self.state.get("volume")

    @property
    def live(self) -> dict[str, Any] | None:
        return self.state.get("live")

    @property
    def mac(self) -> str:
        return str((self.state.get("tv") or {}).get("mac") or "")

    @property
    def model(self) -> str:
        return str((self.state.get("tv") or {}).get("model") or "")

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _changed(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001 - one listener must not stop the others
                _LOGGER.exception("listener failed")

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    async def async_get_state(self, since: int = 0, timeout: float = POLL_TIMEOUT_S) -> dict[str, Any]:
        try:
            async with asyncio.timeout(timeout):
                async with self._session.get(self._url("/api/state"), params={"since": since}, headers=self._headers) as resp:
                    if resp.status == 401:
                        raise CytvAuthError("the TV does not know this Home Assistant (any more)")
                    if resp.status != 200:
                        raise CytvError(f"HTTP {resp.status}")
                    return await resp.json(content_type=None)
        except CytvError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
            raise CytvError(str(err) or type(err).__name__) from err

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"cleanyourtv {self.host}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def wait_first(self, timeout: float) -> bool:
        try:
            async with asyncio.timeout(timeout):
                await self._first.wait()
            return True
        except TimeoutError:
            return False

    async def _run(self) -> None:
        seq = 0
        attempt = 0
        while True:
            try:
                st = await self.async_get_state(seq)
                attempt = 0
                seq = int(st.get("seq") or 0)
                was = self.connected
                self.state = st
                self.connected = True
                self.auth_failed = False
                self._first.set()
                self._changed()
                if not was:
                    _LOGGER.debug("connected to %s", self.host)
                continue
            except CytvAuthError as err:
                _LOGGER.warning("%s: %s; pair again", self.host, err)
                self.auth_failed = True
                self._set_disconnected()
                self._first.set()
                return
            except asyncio.CancelledError:
                raise
            except CytvError as err:
                _LOGGER.debug("%s: %s", self.host, err)
            seq = 0  # after a gap the whole state is asked again
            self._set_disconnected()
            self._first.set()
            await asyncio.sleep(RETRY_S[min(attempt, len(RETRY_S) - 1)])
            attempt += 1

    def _set_disconnected(self) -> None:
        if self.connected:
            self.connected = False
            self._changed()

    # ---- actions ----
    async def async_action(self, t: str, **data: Any) -> None:
        try:
            async with asyncio.timeout(ACTION_TIMEOUT_S):
                async with self._session.post(self._url("/api/action"), json={"t": t, **data}, headers=self._headers) as resp:
                    if resp.status == 401:
                        raise CytvAuthError("the TV does not know this Home Assistant (any more)")
                    body = await resp.json(content_type=None)
        except CytvError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
            raise CytvError(f"the TV did not answer: {err}") from err
        if not isinstance(body, dict) or not body.get("ok"):
            raise CytvError(str((body or {}).get("error") or "the TV refused it"))

    async def async_key(self, key: str) -> None:
        k = str(key).upper()
        if k not in KEYS:
            raise CytvError(f"unknown key {key}")
        await self.async_action("key", k=k)

    async def async_text(self, text: str) -> None:
        await self.async_action("text", s=text)

    async def async_enter(self) -> None:
        await self.async_action("enter")

    async def async_delete(self, count: int = 1) -> None:
        await self.async_action("del", c=int(count))

    async def async_launch(self, app_id: str) -> None:
        await self.async_action("launch", id=app_id)

    async def async_live(self, number: int) -> None:
        await self.async_action("live", num=int(number))

    async def async_move(self, dx: int, dy: int) -> None:
        await self.async_action("move", dx=int(dx), dy=int(dy))

    async def async_click(self) -> None:
        await self.async_action("click")

    async def async_scroll(self, dy: int) -> None:
        await self.async_action("scroll", dy=int(dy))

    async def async_power(self, action: str) -> None:
        if action not in POWER_ACTIONS:
            raise CytvError(f"unknown power action {action}")
        await self.async_action("tvpower", a=action)

    async def async_set_volume(self, level: int) -> None:
        await self.async_action("volume", level=int(level))

    async def async_set_mute(self, mute: bool) -> None:
        await self.async_action("mute", on=bool(mute))

    async def async_unpair(self) -> None:
        with contextlib.suppress(aiohttp.ClientError, TimeoutError, OSError):
            async with asyncio.timeout(5):
                async with self._session.post(self._url("/api/unpair"), headers=self._headers) as resp:
                    await resp.read()

    def wake(self, mac: str | None = None) -> bool:
        mac = mac or self.mac
        if not mac:
            return False
        send_wol(mac, self.host)
        return True

    # ---- lists and pictures ----
    async def _get(self, path: str) -> Any:
        try:
            async with asyncio.timeout(15):
                async with self._session.get(self._url(path), headers=self._headers) as resp:
                    if resp.status == 401:
                        raise CytvAuthError("unauthorized")
                    if resp.status != 200:
                        raise CytvError(f"HTTP {resp.status}")
                    return await resp.json(content_type=None)
        except CytvError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
            raise CytvError(str(err)) from err

    async def async_apps(self) -> list[dict[str, Any]]:
        return [a for a in (await self._get("/api/apps")).get("apps", []) if a.get("id") and a.get("title")]

    async def async_inputs(self) -> list[dict[str, Any]]:
        return [i for i in (await self._get("/api/inputs")).get("inputs", []) if i.get("appId")]

    async def async_channels(self) -> list[dict[str, Any]]:
        return [c for c in (await self._get("/api/channels")).get("channels", []) if c.get("num")]

    async def async_picture(self, path: str) -> tuple[bytes | None, str | None]:
        """A logo (/api/logo/<n>) or an app icon (/api/icon/<id>), for the media player's picture."""
        try:
            async with asyncio.timeout(10):
                async with self._session.get(self._url(path), headers=self._headers) as resp:
                    if resp.status != 200:
                        return None, None
                    return await resp.read(), resp.headers.get("content-type", "image/png")
        except (aiohttp.ClientError, TimeoutError, OSError):
            return None, None
