# CleanYourTV for Home Assistant

Control a rooted LG webOS TV that runs [CleanYourTV](https://github.com/lasharor/cleanyourtv-WebOS) from Home Assistant. It works both ways: the TV reports what it is doing the moment it changes, and Home Assistant controls the TV.

![Dashboard with the TV's media player and the remote](docs/screenshots/ha-dashboard.png)

**What the TV reports:**

- the app in front;
- whether it is **playing or paused** (Netflix, YouTube, Live TV, …);
- the **Live TV channel and programme**;
- the volume and mute;
- whether it is on, has the screen off, or is in standby.

**What Home Assistant can do:**

- turn the TV on and off, and the screen on and off;
- set the volume, play and pause;
- pick the source or a channel;
- send any key or text;
- show the **CleanYourTV Phone remote** as a card.

## Before you start

- **The TV:** an LG webOS TV, rooted, with CleanYourTV installed.
- **Home Assistant:** on the same network as the TV, and either:
  - 2026.11 or newer, which has the built-in **Marketplace**;
  - 2025.1 or newer with [HACS](https://hacs.xyz).
- **Recommended:**
  - give the TV a fixed IP address in your router;
  - switch on **TV On With Mobile** in the TV's settings, so Home Assistant can turn it on.

## Install

### 1. On the TV: the add-on

The add-on is what tells Home Assistant what the TV is doing, so it is needed.

1. In the CleanYourTV manager app, go to **Add-ons › Repositories › Add from your phone**.
2. On the phone, enter `larsoss/cleanyourtv-webos-homeassistant@main/tv-addon`.
3. In **Add-ons**, choose **Home Assistant › Install**.

<details><summary>Over SSH instead</summary>

```sh
node /media/developer/cleanyourtv/cytv-addons.js repo-add larsoss/cleanyourtv-webos-homeassistant@main/tv-addon
node /media/developer/cleanyourtv/cytv-addons.js install homeassistant
```

</details>

### 2. In Home Assistant: the integration

**Home Assistant 2026.11 and newer (Marketplace):**

1. Go to **Settings › Marketplace › Add from link** and enter `larsoss/cleanyourtv-webos-homeassistant`.

   The first time, the Marketplace asks you to connect GitHub. That connection is read-only.
2. Open **CleanYourTV** and choose **Install**.

   No restart is needed: setup starts right away, so continue with step 3.

**Older Home Assistant (HACS):**

1. Go to **HACS › ⋮ › Custom repositories** and add `https://github.com/larsoss/cleanyourtv-webos-homeassistant` as an **Integration**.
2. **Download** it and **restart Home Assistant**.

### 3. Pair, without a code

1. Home Assistant finds the TV by itself: **Settings › Devices & services** shows **CleanYourTV**. Click **Add**.

   If it does not show up, choose **Add integration › CleanYourTV** and enter the TV's IP address. With the Marketplace, the setup it starts after installing asks for the address the same way.
2. On the TV, open the add-on's page **Home Assistant** (in the book next to Home) and choose **Pair Home Assistant**.
3. In Home Assistant, click **Submit** within three minutes.

| On the TV | In Home Assistant |
|---|---|
| ![](docs/screenshots/tv-addon-pairing.png) | ![](docs/screenshots/ha-pair.png) |

## The remote

![The remote: buttons, touchpad, apps, and Live TV with the guide](docs/screenshots/remote-card.png)

The remote comes with the integration, so there is nothing extra to install. You can open it in three ways:

- **Sidebar:** **TV remote**. The ✕ next to the power button takes you back.
- **The TV's device page:** **Visit**.
- **On a dashboard:** go to **Settings › Devices & services › CleanYourTV › ⚙️ › Put the remote on a dashboard**. This adds a view with the remote to the dashboard you choose.

You can also add it as a card yourself:

```yaml
type: custom:cleanyourtv-remote
entity: media_player.lg_tv   # the CleanYourTV media player, not the LG webOS one
theme: auto   # light or dark: auto follows Home Assistant's theme
close: auto   # a ✕ next to the power button: auto = only in a popup (browser_mod, Bubble Card, …), true = always, false = never
```

## What you get

| Entity | What it does |
|---|---|
| **Media player** | State `playing` / `paused` / `on` / `idle` (screen off) / `off`. During Live TV, `media_channel` is the channel and `media_title` is the programme, with a progress bar and the channel logo. Volume, mute, play/pause, channel up/down, and source. |
| **Remote** | `remote.send_command` with key names (`UP`, `ENTER`, `HOME`, `VOLUMEUP`, `RED`, `1`, …) and `text:…`, `launch:<app id>`, `live:<number>`. |
| **Buttons** | Screen off, screen on, standby, restart, shut down (disabled by default). |
| **Select** | Carry on watching: the series and films to pick up, straight from your Jellyfin server (when one is set up). |
| **Sensor** | The power state. |

**Useful attributes** on the media player:

- `app_id`;
- `live_channel_number`, `live_channel_name`;
- `programme_title`, `programme_end`;
- `next_programme_title`.

**Example:** lights up when Netflix is paused.

```yaml
alias: Netflix paused, lights up
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
      entity_id: light.living_room
    data:
      brightness_pct: 60
mode: single
```

## The doorbell on the TV

`cleanyourtv.show_notification` shows a card over whatever is playing: a title, a text and a camera's snapshot. Home Assistant takes the snapshot and sends it along, so the TV needs no address or token of Home Assistant. The card does not take the remote, and leaves after the time you set.

```yaml
alias: Doorbell on the TV
triggers:
  - trigger: state
    entity_id: binary_sensor.doorbell_visitor
    to: "on"
conditions:
  - condition: state
    entity_id: media_player.lg_tv
    state:
      - playing
      - paused
      - "on"
actions:
  - action: cleanyourtv.show_notification
    target:
      entity_id: remote.lg_tv_remote
    data:
      title: Front door
      message: Someone is at the door
      camera: camera.doorbell
      seconds: 20
      position: top-right
mode: single
```

Instead of `camera`, `image_url` takes a picture at an address: one of Home Assistant itself works too (`/local/...`). Without a picture, the card is just text. Needs the add-on on the TV at 0.3.0 or newer.

## Put a title on (Jellyfin)

`cleanyourtv.play` plays a series or film from your own Jellyfin server on the TV. A series starts at the episode you have to watch
next, where you stopped watching it.

```yaml
action: cleanyourtv.play
target:
  entity_id: remote.lg_tv_remote
data:
  title: Reacher
  season: 1      # a season and an episode pick that one; without them, the episode to watch next
  episode: 3
  resume: true   # the default; false starts at the beginning instead of where you stopped
```

### Carry on watching, without writing anything

Two things appear by themselves as soon as the server is set up, so there is no YAML to write:

- **A "Watch" tab in the remote card** (and on the remote page): **Series** or **Films**, as posters of one size with how far you
  got. A film plays at a tap. A series opens on its seasons, where you pick an episode — or press the button at the top to carry on
  with the one you were on. The TV is turned on if it was off. The posters come through Home Assistant, so the server's address and
  key stay out of the browser and the tab also works from outside the house.
- **A "Carry on watching" dropdown** (`select.<your tv>_continue_watching`): the same list as one line each, for a dashboard, a
  button or a voice command. Nothing stays chosen, so the same title can be picked again.

```yaml
type: entities
title: TV
entities:
  - entity: select.lg_tv_continue_watching
    name: Carry on watching
```

The dropdown carries the whole list in its attributes (`series`, `movies`, `items` with title, episode, how far it got and the
poster's id), for a template or a card of your own.

### How it works

The action does not drive the app on the TV. It asks the Jellyfin *server* to play something on the client the TV has open, the
same way the cast button in Jellyfin's web page does:

1. The title is looked up in your library (`/Items?searchTerm=…`), the closest name first. For a series it then asks the server
   which episode is next (`/Shows/NextUp`), or looks up the season and episode you asked for.
2. It looks for the TV among the clients signed in to the server (`/Sessions`). The TV's own address decides, so a phone that is
   signed in as well is never picked by mistake. If the TV is not there, the Jellyfin client is opened on it and the action waits
   up to 25 seconds for it to sign in.
3. `POST /Sessions/<id>/Playing?playCommand=PlayNow` starts it, with the position you had reached.

What there is to carry on with is read every five minutes (and again shortly after something was played): `/Shows/NextUp` for the
series and `/UserItems/Resume` for the films.

So nothing has to be installed on the TV beyond a Jellyfin client. A TV that is off is woken first (Wake-on-LAN), so picking
something to watch does not need the remote as well.

### Which Jellyfin client

Any client works that tells the server it takes media control. These are known, and the one to open is the **Jellyfin client**
option (the list shows which of them are on your TV; any other app id can be typed in):

| Client | App id | |
|---|---|---|
| Jellyfin for webOS (official) | `org.jellyfin.webos` | works |
| [Litefin](https://repo.webosbrew.org/apps/org.litefin.app/) | `org.litefin.app` | works |
| [Moonfin](https://github.com/Moonfin-Client/Smart-TV) | `org.moonfin.webos` | reports media control; not tested here |

If the client you chose is not installed on the TV, one of the others that is gets opened instead. Not sure about a client of your
own? Open it on the TV, then press the cast button in Jellyfin on your phone: if the TV is in that list, this action can play on it.

### Setting it up

**Settings › Devices & services › CleanYourTV › ⚙️ › Jellyfin**:

- **address** of the server, filled in for you: the one Home Assistant's own Jellyfin integration uses, or the server that answers
  on the network (Jellyfin's own clients find a server the same way). Otherwise type it, e.g. `http://192.168.1.10:8096`.
- **API key** from **Jellyfin › Dashboard › API keys**. Your password is never asked; the key stays in Home Assistant and is
  checked while you type it in.
- **user**, whose library is searched and whose watched position is used. With one user on the server it is filled in by itself.
- **Jellyfin client** to open, see above.

Leave the address and the key empty to switch the action off again.

Only Jellyfin for now. What it takes to do the same for Plex, Netflix and the other apps is written down in
[docs/play-a-show.md](docs/play-a-show.md).

## Problems?

| You see | Do this |
|---|---|
| "The TV did not answer" | The TV is on? The **Home Assistant** add-on is installed? Port `8801`? |
| "The TV is not waiting" | First choose **Pair Home Assistant** on the TV, then **Submit**. |
| "Custom element doesn't exist: cleanyourtv-remote" | Reload the page. In the Companion app, close the app fully and open it again. After an **update**, restart Home Assistant first: the Marketplace shows a repair for this. |
| Home Assistant asks to pair again | The TV removed it. Pair again (step 3). |
| Turning on does nothing | Switch on **TV On With Mobile** on the TV. Turn the TV on once with its own remote while Home Assistant is connected. |
| The TV asks something at the first key press | Allow it: the add-on needs the TV's pointer for the keys. |

Still stuck? [Open an issue](https://github.com/larsoss/cleanyourtv-webos-homeassistant/issues) with your TV model and webOS version.

## Good to know

- **Beta versions:**
  - **Marketplace:** go to **Settings › Devices & services › Marketplace** and open **CleanYourTV**. Enable the **Pre-release** entity (it is disabled by default) and switch it on.
  - **HACS:** switch on **Show beta versions**.
  - **On the TV:** use `…@Beta/tv-addon` as the repository address.
- **Updates** appear under **Settings › Updates**. After an update, restart Home Assistant.
- **Privacy:** everything stays on your network.
  - Only a Home Assistant you paired on the TV can use the add-on.
  - Your IPTV stream address (which can hold your provider's login) never leaves the TV.
- **Tested on:** LG 65UP77006LB, webOS 6.5.3. Other webOS versions should work, but have not been tested yet.

## Development

```sh
pip install -r requirements_test.txt && python -m pytest tests             # needs node
node tv-addon/make-index.js                                                # after changing the add-on
CYTV_SRC=/path/to/cleanyourtv-WebOS node tools/build-card.js               # rebuild the remote card
```

**Credits:**

- [CleanYourTV](https://github.com/lasharor/cleanyourtv-WebOS) by Stefan (lasharor).
- The Phone remote, which the remote card and the add-on's keys are built on, by [@Edenik](https://github.com/Edenik) (MIT).
