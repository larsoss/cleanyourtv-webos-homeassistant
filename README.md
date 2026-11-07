# CleanYourTV for Home Assistant

A rooted LG webOS TV with [CleanYourTV](https://github.com/lasharor/cleanyourtv-WebOS) in Home Assistant, **both ways**. The TV tells Home Assistant the moment something changes, and Home Assistant controls the TV.

**What the TV reports, as it happens (no polling):**

- the app in front;
- whether its video **plays or is paused**: Netflix, YouTube, Live TV and every app that plays through the TV's own media pipeline;
- the **Live TV channel** you watch (CleanYourTV's M3U playlist), with the **programme from the guide** and the channel logo;
- the **volume** and **mute**;
- the **power state**: on, screen off, standby.

**What Home Assistant can do:**

- turn the TV on (Wake-on-LAN, or the screen back on) and off (standby);
- set the volume, mute, play, pause, stop, and channel up and down;
- pick an input, app or Live TV channel as the source;
- send every remote key, text, and pointer moves;
- screen off and on, restart, shut down.

It is one integration with one device per TV:

- **media player:** the state, what plays, the source and the volume;
- **remote:** keys and actions;
- **buttons** for power;
- **sensor** for the power state.

## How it works

The repository has two parts:

| Part | Where | What |
| --- | --- | --- |
| **TV add-on "Home Assistant"** | `tv-addon/` (a CleanYourTV add-on repository) | Runs inside CleanYourTV's service on the TV. Follows LG's own services (app manager, `com.webos.media`, audio, power) with luna subscriptions while Home Assistant is connected, and answers on port 8801. |
| **Integration "CleanYourTV"** | `custom_components/cleanyourtv` (HACS) | Pairs once with a 6-digit code, then keeps a long poll open: the TV answers the moment something changes. |

The Live TV channel is found on the TV itself. The address of the stream that plays is matched against your playlist. That address can contain your provider's credentials, so it never leaves the TV: Home Assistant gets only the number, name, group, programme and logo.

Checked on an LG 65UP77006LB (webOS 6.5.3, firmware 03.53.45) with read-only calls:

- Netflix reports `paused` and `playing`;
- Live TV in Home reports `loaded` then `playing`, and its stream matched the channel, with the programme from the guide;
- the volume reports every step and mute;
- app switches arrive at once.

The add-on and the integration together have not run on a TV yet. The tests run the add-on on a computer, with a fake TV behind it.

## Install

### 1. On the TV: the add-on

1. Manager app > **Add-ons** > **Repositories** > **Add from your phone**. Enter `larsoss/cleanyourtv-webos-homeassistant@main/tv-addon` and confirm that you trust it.

   Over SSH instead: `cytv-addons repo-add larsoss/cleanyourtv-webos-homeassistant@main/tv-addon`.
2. Install **Home Assistant** from the Add-ons list.

   Over SSH: `cytv-addons install homeassistant`.

   The manager shows what the add-on may do before it installs. Like every add-on of `kind: service`, it runs as root on the TV.

### 2. In Home Assistant: the integration

1. HACS > the three dots > **Custom repositories**: add `https://github.com/larsoss/cleanyourtv-webos-homeassistant`, type **Integration**. Install **CleanYourTV** and restart Home Assistant.
2. On the TV, open the add-on's page (**Home Assistant**, in the book next to Home) and choose **Pair Home Assistant**. It shows a 6-digit code for three minutes.
3. In Home Assistant: **Settings > Devices & services > Add integration > CleanYourTV**. Enter the TV's IP address and the code.

The add-on's page lists the paired Home Assistants and can remove one. If you remove Home Assistant there, Home Assistant asks you to pair again. If you delete the integration in Home Assistant, the TV forgets it too. If the TV gets a new IP address, use **Reconfigure**.

To turn the TV on from standby, switch **TV On With Mobile** (Wake-on-LAN) on in the TV's settings, and best give the TV a fixed IP address. The packet goes to the TV's own address as well as a broadcast, so it also works over Wi-Fi.

**Keys on webOS 5 and 6:** the add-on presses keys the way the Phone remote add-on does. The first time, the TV may ask on screen whether to allow the connection.

## The media player

| State | When |
| --- | --- |
| `playing` / `paused` | the video in front plays or is paused (any app that plays through the TV) |
| `buffering` | a video is loading |
| `on` | on, nothing plays |
| `idle` | the screen is off (the TV runs) |
| `off` | standby, or not reachable |

During Live TV:

- `media_channel` is `24 Viaplay F1`;
- `media_title` is the programme (`F1 Kwalificatie`);
- `media_duration` and `media_position` follow the programme from the guide;
- the picture is the channel logo.

The attributes also have `live_channel_number`, `live_channel_name`, `live_channel_group`, `programme_title`, `programme_start`, `programme_end` and `programme_description`.

For other apps, `app_id` and `app_name` say what is in front and the picture is the app's icon.

### Automation: dim the lights when Netflix pauses

```yaml
alias: TV paused, lights up
triggers:
  - trigger: state
    entity_id: media_player.lg_tv
    to: paused
conditions:
  - condition: state
    entity_id: media_player.lg_tv
    attribute: app_id
    state: netflix
actions:
  - action: light.turn_on
    target:
      entity_id: light.woonkamer
    data:
      brightness_pct: 60
mode: single
```

### Automation: a message when the race starts

```yaml
alias: F1 is on
triggers:
  - trigger: state
    entity_id: media_player.lg_tv
    attribute: live_channel_number
    to: 24
actions:
  - action: notify.notify
    data:
      message: "Nu op tv: {{ state_attr('media_player.lg_tv', 'programme_title') }}"
mode: single
```

## The remote

`remote.send_command` takes key names:

```
UP DOWN LEFT RIGHT ENTER BACK HOME MENU EXIT INFO POWER VOLUMEUP VOLUMEDOWN MUTE CHANNELUP CHANNELDOWN
PLAY PAUSE STOP REWIND FASTFORWARD RED GREEN YELLOW BLUE 0-9
```

It also takes a few commands of its own:

| Command | What it does |
| --- | --- |
| `text:<text>` | types into the text field that is open on the TV |
| `enter`, `delete`, `click` | Enter, delete one character, a pointer click |
| `launch:<app id>` | opens an app or input (`launch:com.webos.app.hdmi1`, `launch:netflix`) |
| `live:<number>` | Live TV of CleanYourTV on that channel |

Actions:

- `cleanyourtv.send_text`
- `cleanyourtv.launch_app`
- `cleanyourtv.live_channel`
- `cleanyourtv.tv_power`: `off`, `on`, `standby`, `reboot` or `shutdown`
- `cleanyourtv.pointer`
- `cleanyourtv.refresh_lists`

`media_player.play_media` takes `media_content_type: app` with an app id, or `channel` with a number. The options of the integration can add the Live TV channels to the source list.

### A dashboard card

Replace `media_player.lg_tv` and `remote.lg_tv_remote` with your own entity ids.

```yaml
type: vertical-stack
cards:
  - type: media-control
    entity: media_player.lg_tv
  - type: grid
    columns: 3
    square: false
    cards:
      - type: button
        icon: mdi:power
        name: Aan/uit
        tap_action:
          action: perform-action
          perform_action: media_player.toggle
          target:
            entity_id: media_player.lg_tv
      - type: button
        icon: mdi:chevron-up
        name: Omhoog
        tap_action:
          action: perform-action
          perform_action: remote.send_command
          target:
            entity_id: remote.lg_tv_remote
          data:
            command: UP
      - type: button
        icon: mdi:home
        name: Home
        tap_action:
          action: perform-action
          perform_action: remote.send_command
          target:
            entity_id: remote.lg_tv_remote
          data:
            command: HOME
      - type: button
        icon: mdi:chevron-left
        name: Links
        tap_action:
          action: perform-action
          perform_action: remote.send_command
          target:
            entity_id: remote.lg_tv_remote
          data:
            command: LEFT
      - type: button
        icon: mdi:circle-medium
        name: OK
        tap_action:
          action: perform-action
          perform_action: remote.send_command
          target:
            entity_id: remote.lg_tv_remote
          data:
            command: ENTER
      - type: button
        icon: mdi:chevron-right
        name: Rechts
        tap_action:
          action: perform-action
          perform_action: remote.send_command
          target:
            entity_id: remote.lg_tv_remote
          data:
            command: RIGHT
      - type: button
        icon: mdi:arrow-left
        name: Terug
        tap_action:
          action: perform-action
          perform_action: remote.send_command
          target:
            entity_id: remote.lg_tv_remote
          data:
            command: BACK
      - type: button
        icon: mdi:chevron-down
        name: Omlaag
        tap_action:
          action: perform-action
          perform_action: remote.send_command
          target:
            entity_id: remote.lg_tv_remote
          data:
            command: DOWN
      - type: button
        icon: mdi:television-classic
        name: Live TV
        tap_action:
          action: perform-action
          perform_action: remote.send_command
          target:
            entity_id: remote.lg_tv_remote
          data:
            command: live:1
```

## Good to know

- Nothing leaves your network. The connection is plain HTTP on your own network, and every call needs the token from the pairing. Web pages in a browser are refused, because browsers send `Origin`.
- The TV follows its services only while Home Assistant is connected. Two minutes after the last request, the subscriptions stop.
- **Live TV:** if a stream's address is not in the playlist as it is (a redirect, say), the channel Live TV marked as played last is used.

## Development

```sh
pip install -r requirements_test.txt
python -m pytest tests                              # the integration against the add-on with a fake TV (needs node)
node tv-addon/make-index.js                         # after every change of the add-on (and raise its version)
CYTV_SRC=/path/to/cleanyourtv-WebOS node tests/addon_manifest.test.js
```

The add-on runs on Node.js 8.12 (webOS 5 and 6). Its key code (`remotekeys.js`, `ws.js`) is copied from the Phone remote add-on by [@Edenik](https://github.com/Edenik) (MIT).

---

## Nederlands

Met deze integratie ziet Home Assistant meteen wat je tv doet:

- welke app er voorop staat;
- of er iets **speelt of op pauze staat**: Netflix, YouTube, Live TV en elke app die via de tv afspeelt;
- welke **Live TV-zender** je kijkt, met het **programma** uit de gids en het logo;
- het **volume** en **mute**;
- of de tv aan, met scherm uit of in stand-by staat.

Andersom bedient Home Assistant de tv: aan/uit, volume, afspelen/pauze, bron, alle toetsen en tekst. Alles zit in één integratie, met de afstandsbediening erin.

**Installeren:**

1. Op de tv: Add-ons > Repositories > `larsoss/cleanyourtv-webos-homeassistant@main/tv-addon`, en installeer daarna **Home Assistant**.
2. In HACS: voeg deze repository toe als aangepaste repository (type Integratie) en installeer **CleanYourTV**.
3. Op de tv: open de pagina van de add-on en kies **Home Assistant koppelen**.
4. In Home Assistant: voeg **CleanYourTV** toe met het IP-adres van de tv en de code.
