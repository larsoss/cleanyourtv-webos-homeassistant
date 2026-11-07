"""The integration in Home Assistant against the TV add-on with a fake TV behind it."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cleanyourtv import config_flow
from custom_components.cleanyourtv.const import CONF_DEVICE_NAME, CONF_LIVE_SOURCES, CONF_MAC, CONF_TOKEN, DOMAIN

from .harness import available

pytestmark = pytest.mark.skipif(not available(), reason="needs node")

MP = "media_player.127_0_0_1"
RM = "remote.127_0_0_1_remote"


async def until(cond, timeout: float = 5) -> None:
    for _ in range(int(timeout / 0.05)):
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


def st(hass: HomeAssistant, eid: str):
    return hass.states.get(eid)


async def test_pair_and_follow(hass: HomeAssistant, addon) -> None:
    await addon.run("close", "closed")
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: addon.port, CONF_DEVICE_NAME: "HA"}
    )
    assert r["errors"] == {"base": "not_waiting"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: 1, CONF_DEVICE_NAME: "HA"})
    assert r["errors"] == {"base": "cannot_connect"}
    await addon.open_pairing()
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: addon.port, CONF_DEVICE_NAME: "HA"}
    )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    entry = r["result"]
    assert entry.data[CONF_TOKEN]
    await hass.async_block_till_done()
    ents = {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert {MP, RM, "sensor.127_0_0_1_power_state", "button.127_0_0_1_screen_off"} <= ents

    # what the TV pushes
    await addon.command("power Active")
    await addon.command("app netflix")
    await addon.command("media netflix playing")
    await addon.command("volume 12 false")
    await until(lambda: st(hass, MP).state == "playing")
    await until(lambda: st(hass, MP).attributes.get("source") == "Netflix")
    a = st(hass, MP).attributes
    assert a["app_id"] == "netflix" and a["volume_level"] == 0.12 and a["is_volume_muted"] is False
    await addon.command("media netflix paused")
    await until(lambda: st(hass, MP).state == "paused")
    await addon.command("volume 12 true")
    await until(lambda: st(hass, MP).attributes.get("is_volume_muted") is True)

    await addon.command("pipeline http://iptv.example/live/user/pass/24.ts")
    await addon.command("app com.webos.app.home")
    await addon.command("media com.webos.app.home playing")
    await until(lambda: st(hass, MP).attributes.get("media_channel") == "24 Viaplay F1")
    a = st(hass, MP).attributes
    assert a["media_title"] == "F1 Kwalificatie" and a["app_name"] == "Live TV" and a["live_channel_number"] == 24
    assert a["media_content_type"] == "channel" and a["media_duration"] > 0

    await addon.command("power Screen Off")
    await until(lambda: st(hass, MP).state == "idle")
    await hass.services.async_call("media_player", "turn_on", {"entity_id": MP}, blocking=True)
    await addon.wait_for(lambda e: e.get("uri", "").endswith("/turnOnScreen"))
    await addon.command("power Active Standby")
    await until(lambda: st(hass, MP).state == "off")
    assert st(hass, "sensor.127_0_0_1_power_state").state == "active_standby"
    await addon.command("power Active")
    await until(lambda: st(hass, MP).state == "playing")

    # control
    await hass.services.async_call("media_player", "volume_set", {"entity_id": MP, "volume_level": 0.3}, blocking=True)
    await addon.wait_for(lambda e: e.get("uri", "").endswith("/setVolume") and e["params"] == {"volume": 30})
    await hass.services.async_call("media_player", "volume_mute", {"entity_id": MP, "is_volume_muted": False}, blocking=True)
    await addon.wait_for(lambda e: e.get("uri", "").endswith("/setMute") and e["params"] == {"mute": False})
    await hass.services.async_call("media_player", "media_pause", {"entity_id": MP}, blocking=True)
    await addon.wait_for(lambda e: e == {"ev": "key", "k": "PAUSE"})
    await until(lambda: st(hass, MP).attributes.get("source_list"))
    assert st(hass, MP).attributes["source_list"] == ["HDMI 1", "Netflix", "YouTube"]
    await hass.services.async_call("media_player", "select_source", {"entity_id": MP, "source": "HDMI 1"}, blocking=True)
    await addon.wait_for(lambda e: e.get("ev") == "launch" and e["body"] == {"id": "com.webos.app.hdmi1"})
    await hass.services.async_call("remote", "send_command", {"entity_id": RM, "command": ["HOME", "text:abc"]}, blocking=True)
    await addon.wait_for(lambda e: e == {"ev": "text", "s": "abc"})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("remote", "send_command", {"entity_id": RM, "command": ["BOGUS"]}, blocking=True)
    await hass.services.async_call(DOMAIN, "live_channel", {"entity_id": RM, "channel": 24}, blocking=True)
    await addon.wait_for(lambda e: e == {"ev": "key", "k": "4"})
    await hass.services.async_call("button", "press", {"entity_id": "button.127_0_0_1_screen_off"}, blocking=True)
    await addon.wait_for(lambda e: e.get("uri", "").endswith("/turnOffScreen"))

    # the channel logo / app icon is served through Home Assistant
    mp = hass.data["entity_components"]["media_player"].get_entity(MP)
    await addon.command("media netflix playing")
    await addon.command("app netflix")
    await until(lambda: st(hass, MP).attributes.get("app_id") == "netflix" and not st(hass, MP).attributes.get("media_channel"))
    assert (await mp.async_get_media_image())[0] == b"PNG"

    # Live TV channels as sources
    r = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(r["flow_id"], {CONF_LIVE_SOURCES: True})
    await hass.async_block_till_done()
    await until(lambda: "Live: 24 Viaplay F1" in (st(hass, MP).attributes.get("source_list") or []))

    # removed on the TV: Home Assistant asks to pair again
    await addon.command("revoke")
    await until(lambda: any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress()), 35)
    flow = next(f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == "reauth")
    await addon.open_pairing()
    r = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_DEVICE_NAME: "HA"})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    await until(lambda: entry.runtime_data.client.connected)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_tv_unreachable_still_sets_up(hass: HomeAssistant, socket_enabled) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="TV", data={CONF_HOST: "127.0.0.1", CONF_PORT: 1, CONF_TOKEN: "00000000." + "0" * 32, CONF_MAC: ""}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("media_player.tv").state == "off"
    assert hass.states.get("sensor.tv_power_state").state == "unreachable"
    with pytest.raises(Exception, match="MAC"):
        await hass.services.async_call("media_player", "turn_on", {"entity_id": "media_player.tv"}, blocking=True)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_found_on_the_network(hass: HomeAssistant, addon, monkeypatch) -> None:
    from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

    monkeypatch.setattr(config_flow, "DEFAULT_PORT", addon.port)
    info = SsdpServiceInfo(
        ssdp_usn="uuid:tv::urn:lge-com:service:webos-second-screen:1",
        ssdp_st="urn:lge-com:service:webos-second-screen:1",
        ssdp_location="http://127.0.0.1:1856/",
        upnp={"friendlyName": "LG TV"},
    )
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_SSDP}, data=info)
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "confirm"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_DEVICE_NAME: "HA"})
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["data"][CONF_PORT] == addon.port
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(r["result"].entry_id)

    # an LG TV without the add-on is not offered
    monkeypatch.setattr(config_flow, "DEFAULT_PORT", 1)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_SSDP}, data=info)
    assert r["type"] is FlowResultType.ABORT and r["reason"] in ("not_cleanyourtv", "already_configured")


async def test_remote_card_backend(hass: HomeAssistant, addon, hass_ws_client, hass_client_no_auth) -> None:
    """The card's WebSocket commands and its pictures (the card itself was checked in Chromium with a stand-in for Home Assistant)."""
    await addon.open_pairing()
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: addon.port, CONF_DEVICE_NAME: "HA"}
    )
    entry = r["result"]
    await hass.async_block_till_done()
    await until(lambda: st(hass, MP).attributes.get("connected") is True)

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "cleanyourtv/card", "entity_id": MP})
    card = (await ws.receive_json())["result"]
    assert card["entry_id"] == entry.entry_id and len(card["secret"]) == 32

    await ws.send_json({"id": 2, "type": "cleanyourtv/action", "entry_id": entry.entry_id, "action": {"t": "key", "k": "HOME", "n": 7}})
    assert (await ws.receive_json())["result"] == {"ok": True, "error": ""}
    await addon.wait_for(lambda e: e == {"ev": "key", "k": "HOME"})
    await ws.send_json({"id": 3, "type": "cleanyourtv/action", "entry_id": entry.entry_id, "action": {"t": "selfdestruct"}})
    assert (await ws.receive_json())["result"]["ok"] is False
    await ws.send_json({"id": 4, "type": "cleanyourtv/list", "entry_id": entry.entry_id, "kind": "live"})
    assert [c["num"] for c in (await ws.receive_json())["result"]["channels"]] == [1, 24]
    await ws.send_json({"id": 5, "type": "cleanyourtv/list", "entry_id": entry.entry_id, "kind": "apps"})
    assert (await ws.receive_json())["result"]["apps"][0]["id"] == "netflix"

    client = await hass_client_no_auth()
    resp = await client.get(f"/api/cleanyourtv/{entry.entry_id}/icon/netflix?t={card['secret']}")
    assert resp.status == 200 and await resp.read() == b"PNG"
    resp = await client.get(f"/api/cleanyourtv/{entry.entry_id}/icon/netflix?t=wrong")
    assert resp.status == 401
    resp = await client.get("/cleanyourtv_static/cleanyourtv-remote.js")
    assert resp.status == 200 and "cleanyourtv-remote" in await resp.text()
    resp = await client.get("/cleanyourtv_static/pages/nl.html")
    assert resp.status == 200 and "Afstandsbediening" in await resp.text()
    assert await hass.config_entries.async_unload(entry.entry_id)
