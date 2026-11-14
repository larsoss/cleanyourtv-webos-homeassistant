# Research: "put on Reacher" from Home Assistant

couch-tv lets you ask for a show by name and starts it in the right app. This page looks at what that takes on a rooted LG TV with
CleanYourTV, app by app, and proposes how to build it in this integration.

**Phase 1 is built**: `cleanyourtv.play` plays a title from your own Jellyfin server. Phases 2 and 3 are not.

## Two steps

1. **Where is it?** From a title to an app and an id in that app.
2. **Start it there.** Open that app on that title, ideally playing.

## Step 2, app by app

| App on the TV | How it can start a title | Verdict |
|---|---|---|
| **Jellyfin** (`org.jellyfin.webos`) | Not through the TV: through the Jellyfin server. The app is the Jellyfin web client, which takes remote control. The server lists it as a session (`GET /Sessions`), and `POST /Sessions/{id}/Playing?playCommand=PlayNow&itemIds=…` starts an item on it. The app must be open first, so: open it, wait for its session, send the command. | **Works**, and the most reliable: our own library, exact items, the next episode from the server. |
| **Plex** | Plex Companion: the server or a controller asks the Plex app to play. The LG app is a receiver, but reports are mixed (Home Assistant's `play_media` on Plex for LG fails for some), and the mobile apps changed how Companion works in 2025. | **Possible**, less reliable. Second after Jellyfin. |
| **Netflix** | `applicationManager/launch` with `params: {contentTarget: "https://www.netflix.com/watch/<id>"}` (the id of a title or an episode). | **Works** once the Netflix id is known. |
| **YouTube** | `params: {contentTarget: "v=<video id>"}`. | **Works** for a video. |
| **Prime Video, Disney+, Videoland, NPO Start, SkyShowtime, NLZIET, Pathé Thuis** | No documented launch parameters. Reports say a web link as `contentTarget` does not work for Prime Video and Disney+. | **Unknown**: to try on the TV, one app at a time. Fallback: open the app on its search with the title typed in (our add-on can type), which leaves one press. |

## Which Jellyfin app on the TV

`cleanyourtv.play` does not talk to the app at all: it asks the Jellyfin *server* to play something on the session the app has open.
So any client works as long as it reports to the server that it takes media control (`SupportsMediaControl` in what it posts to
`POST /Sessions/Capabilities/Full`) and acts on the server's `Play` message. The app to open is an option
(`jellyfin_app`, the default is `org.jellyfin.webos`).

| Client on the TV | App id | Takes a play command? |
|---|---|---|
| **Jellyfin for webOS** (official) | `org.jellyfin.webos` | **Yes** — it is the Jellyfin web client. Tested on the TV. |
| **Litefin** | `org.litefin.app` | **Yes**, by its code: it posts `SupportsMediaControl: true` and handles `Play` → `PlayNow` with `StartPositionTicks` ([WebSocketHandler.js](https://github.com/MoazSalem/litefin/blob/main/src/api/WebSocketHandler.js)). Not tested here. |
| **Moonfin** | `org.moonfin.webos` | **Probably**: it carries a `services/remoteControl.js` and posts `SupportsMediaControl`. Not tested here. |
| **Breezyfin** | — | **Probably not**: nothing in its code posts `SupportsMediaControl`, so the server would not offer it as a target. |

The quickest test for any of them: open the client on the TV, then on another device open Jellyfin web, press the cast icon and see
whether the TV is listed. If it is, this action can play on it.

## Step 1: from a title to an app

- **Own library (Jellyfin, Plex):** the server's own search (`/Items?searchTerm=…`), exact and private.
- **Streaming services:** couch-tv uses JustWatch. JustWatch has no public API; its GraphQL endpoint is used by many projects but can
  change without notice, and their terms ask for credit. It gives the services per country (NL) and, for Netflix, the id.
- **Order:** own library first (it plays at once), then the services you have installed.

## Proposal

**Phase 1, Jellyfin** (this is where it works end to end):

- Settings of the integration: the Jellyfin server address and an API key (Jellyfin > Dashboard > API keys).
- Action `cleanyourtv.play`: `title`, optional `season`/`episode`; finds the series or film, takes the next unplayed episode (or resumes),
  opens Jellyfin on the TV, waits for its session (up to 15 s), and starts it.
- Also from the remote card: a search field on the Live/Apps tab.

**Phase 2, Netflix and YouTube:** `cleanyourtv.play` with `app: netflix` and an id or a `netflix.com/title/…` link; YouTube with a
video link. Optional JustWatch lookup (country NL) to find the Netflix id from a title, off unless switched on.

**Phase 3, the rest:** try launch parameters per app on the TV; where none work, open the app's search with the title typed.

## What is needed to start

- For phase 1: the Jellyfin server address and an API key, and a moment when the TV is free to test.
