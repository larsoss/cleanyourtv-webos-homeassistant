"""The client against the TV add-on (with a fake TV behind it)."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from custom_components.cleanyourtv import client as c

from .harness import Addon, available

pytestmark = [pytest.mark.skipif(not available(), reason="needs node"), pytest.mark.usefixtures("socket_enabled")]


def test_magic_packet() -> None:
    p = c.magic_packet("A4:CE:DA:33:FB:C8")
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:12] == bytes.fromhex("a4ceda33fbc8")
    with pytest.raises(ValueError):
        c.magic_packet("nope")


async def until(cond, timeout: float = 5) -> None:
    for _ in range(int(timeout / 0.05)):
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


async def test_pair_follow_and_act() -> None:
    addon = await Addon().start()
    try:
        async with aiohttp.ClientSession() as s:
            hello = await c.async_hello(s, "127.0.0.1", addon.port)
            assert hello["service"] == "cleanyourtv-homeassistant" and hello["open"] is True
            token, name = await c.async_pair(s, "127.0.0.1", addon.port, "Home Assistant")
            assert name == "Home Assistant"
            # one Home Assistant per press of "Pair Home Assistant", as with a Hue bridge
            with pytest.raises(c.CytvPairError) as closed:
                await c.async_pair(s, "127.0.0.1", addon.port, "HA")
            assert closed.value.reason == "not_waiting"
            assert (await c.async_hello(s, "127.0.0.1", addon.port))["open"] is False
            # "Pair without asking" on the TV: no press needed
            await addon.run("trust on", "trust")
            assert (await c.async_hello(s, "127.0.0.1", addon.port))["open"] is True
            token2, _ = await c.async_pair(s, "127.0.0.1", addon.port, "HA 2")
            await addon.run("trust off", "trust")
            with pytest.raises(c.CytvPairError):
                await c.async_pair(s, "127.0.0.1", addon.port, "HA 3")
            await c.CytvTV(s, "127.0.0.1", addon.port, token2).async_unpair()

            tv = c.CytvTV(s, "127.0.0.1", addon.port, token)
            tv.start()
            assert await tv.wait_first(5) and tv.connected
            await addon.wait_for(lambda e: e.get("ev") == "subscribe" and "com.webos.media" in e["uri"])

            # the TV pushes: the long poll answers the moment something changes
            await addon.command("app netflix")
            await addon.command("media netflix paused")
            await until(lambda: tv.app == "netflix" and tv.media.get("state") == "paused")
            await addon.command("volume 12 false")
            await until(lambda: tv.volume and tv.volume["level"] == 12 and tv.volume["mute"] is False)
            await addon.command("volume 12 true")
            await until(lambda: tv.volume["mute"] is True)
            await addon.command("power Active")
            await until(lambda: tv.power_state == "Active")

            # Live TV: the stream is matched against the playlist, the guide gives the programme
            await addon.command("pipeline http://iptv.example/live/user/pass/24.ts")
            await addon.command("app com.webos.app.home")
            await addon.command("media com.webos.app.home playing")
            await until(lambda: (tv.live or {}).get("num") == 24)
            assert tv.live["name"] == "Viaplay F1" and tv.live["programme"]["title"] == "F1 Kwalificatie"
            assert "user/pass" not in str(tv.state)  # the stream's address (the provider's key) never leaves the TV
            # a stream that is not in the playlist as it is: the channel Live TV played last
            await addon.command("pipeline http://elsewhere.example/x.m3u8")
            await addon.command("media com.webos.app.home paused")
            await until(lambda: (tv.live or {}).get("num") == 1)
            await addon.command("media netflix playing")
            await until(lambda: tv.live is None)

            await tv.async_key("up")
            await addon.wait_for(lambda e: e == {"ev": "key", "k": "UP"})
            await tv.async_text("hallo")
            await addon.wait_for(lambda e: e == {"ev": "text", "s": "hallo"})
            await tv.async_launch("netflix")
            await addon.wait_for(lambda e: e.get("ev") == "launch" and e["body"] == {"id": "netflix"})
            await tv.async_live(2)
            await addon.wait_for(lambda e: e == {"ev": "key", "k": "2"})
            await tv.async_set_volume(20)
            await addon.wait_for(lambda e: e.get("uri", "").endswith("/setVolume") and e["params"] == {"volume": 20})
            await tv.async_set_mute(True)
            await addon.wait_for(lambda e: e.get("uri", "").endswith("/setMute") and e["params"] == {"mute": True})
            await tv.async_power("on")
            await addon.wait_for(lambda e: e.get("uri", "").endswith("/turnOnScreen"))
            with pytest.raises(c.CytvError):
                await tv.async_key("SELFDESTRUCT")

            assert {a["id"] for a in await tv.async_apps()} == {"netflix", "youtube.leanback.v4"}
            assert (await tv.async_inputs())[0]["appId"] == "com.webos.app.hdmi1"
            assert [ch["num"] for ch in await tv.async_channels()] == [1, 24]
            assert (await tv.async_picture("/api/icon/netflix"))[0] == b"PNG"

            # removed on the TV: the next poll is refused and the client stops
            await addon.command("revoke")
            await until(lambda: tv.auth_failed, 30)
            assert not tv.connected
            with pytest.raises(c.CytvAuthError):
                await tv.async_apps()
            await tv.stop()
    finally:
        await addon.stop()


async def test_not_the_addon() -> None:
    async with aiohttp.ClientSession() as s:
        with pytest.raises(c.CytvError):
            await c.async_hello(s, "127.0.0.1", 1)


async def test_unpair_and_no_web_pages() -> None:
    addon = await Addon().start()
    try:
        async with aiohttp.ClientSession() as s:
            token, _ = await c.async_pair(s, "127.0.0.1", addon.port, "HA")
            # a web page in a browser on the network cannot use it (browsers send Origin)
            async with s.get(
                f"http://127.0.0.1:{addon.port}/api/state", headers={"Origin": "http://evil.example", "Authorization": f"Bearer {token}"}
            ) as r:
                assert r.status == 403
            async with s.get(f"http://127.0.0.1:{addon.port}/api/state", headers={"Authorization": "Bearer 00000000." + "0" * 32}) as r:
                assert r.status == 401
            tv = c.CytvTV(s, "127.0.0.1", addon.port, token)
            await tv.async_unpair()
            with pytest.raises(c.CytvAuthError):
                await tv.async_get_state(0, timeout=5)
    finally:
        await addon.stop()
