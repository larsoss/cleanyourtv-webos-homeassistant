"""A small stand-in for a Jellyfin server: just the calls the play action makes.

It answers like Jellyfin does for one user, one film, one series with two episodes, and a session of the TV's app that appears only
after the app has been "opened" (app_open), so the waiting of the play action is exercised. Episode 2 was half watched, so the
position the action sends along is exercised too.
"""

from __future__ import annotations

from aiohttp import web

USER = {"Id": "u1", "Name": "lars"}
MOVIE = {"Id": "m1", "Name": "Heat", "Type": "Movie", "ProductionYear": 1995}
SERIES = {"Id": "s1", "Name": "Reacher", "Type": "Series"}
EPISODES = [
    {
        "Id": "e1",
        "Name": "Welcome to Margrave",
        "Type": "Episode",
        "IndexNumber": 1,
        "ParentIndexNumber": 1,
        "SeriesName": "Reacher",
        "SeriesId": "s1",
        "SeasonId": "se1",
        "RunTimeTicks": 30_000_000_000,
        "UserData": {"PlaybackPositionTicks": 0, "Played": True},  # watched to the end
    },
    {
        "Id": "e2",
        "Name": "First Dance",
        "Type": "Episode",
        "IndexNumber": 2,
        "ParentIndexNumber": 1,
        "SeriesName": "Reacher",
        "SeriesId": "s1",
        "SeasonId": "se1",
        "RunTimeTicks": 30_000_000_000,
        "UserData": {"PlaybackPositionTicks": 7_200_000_000, "Played": False},  # 12 minutes in
    },
]
NEXT_UP = EPISODES[1]
# a film that was started and not finished: 20 of its 100 minutes
STARTED_MOVIE = {
    "Id": "m2",
    "Name": "Sicario",
    "Type": "Movie",
    "ProductionYear": 2015,
    "RunTimeTicks": 60_000_000_000,
    "UserData": {"PlaybackPositionTicks": 12_000_000_000, "Played": False},
}


class JellyfinFake:
    """Start it, read .url, and let the test say when the TV's app has signed in."""

    def __init__(self) -> None:
        self.key = "test-key"
        self.app_open = False  # no session of the TV's app until the app is opened
        self.played: list[tuple[str, str, int]] = []  # (session id, item id, position in ticks)
        self.calls: list[str] = []
        self._runner: web.AppRunner | None = None
        self.url = ""

    async def start(self) -> JellyfinFake:
        app = web.Application()
        app.router.add_get("/Users", self._users)
        app.router.add_get("/Items", self._items)
        app.router.add_get("/Shows/NextUp", self._next_up)
        app.router.add_get("/UserItems/Resume", self._resume)
        app.router.add_get("/Items/{id}", self._item)
        app.router.add_get("/Items/{id}/Images/Primary", self._poster)
        app.router.add_get("/Shows/{sid}/Episodes", self._episodes)
        app.router.add_get("/Shows/{sid}/Seasons", self._seasons)
        app.router.add_get("/Sessions", self._sessions)
        app.router.add_post("/Sessions/{id}/Playing", self._playing)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        return self

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    def _ok(self, request: web.Request) -> bool:
        return f'Token="{self.key}"' in request.headers.get("Authorization", "")

    async def _users(self, request: web.Request) -> web.Response:
        self.calls.append("Users")
        if not self._ok(request):
            return web.json_response({"error": "no"}, status=401)
        return web.json_response([USER])

    async def _items(self, request: web.Request) -> web.Response:
        self.calls.append("Items")
        if not self._ok(request):
            return web.json_response({"error": "no"}, status=401)
        term = (request.query.get("searchTerm") or "").lower()
        hits = [i for i in (MOVIE, SERIES) if term in i["Name"].lower()]
        return web.json_response({"Items": hits})

    async def _next_up(self, request: web.Request) -> web.Response:
        self.calls.append("NextUp")
        return web.json_response({"Items": [NEXT_UP]})

    async def _resume(self, request: web.Request) -> web.Response:
        self.calls.append("Resume")
        return web.json_response({"Items": [STARTED_MOVIE]})

    async def _item(self, request: web.Request) -> web.Response:
        self.calls.append("Item")
        if not self._ok(request):
            return web.json_response({"error": "no"}, status=401)
        want = request.match_info["id"]
        for i in (MOVIE, SERIES, STARTED_MOVIE, *EPISODES):
            if i["Id"] == want:
                return web.json_response(i)
        return web.json_response({"error": "no"}, status=404)

    async def _poster(self, request: web.Request) -> web.Response:
        self.calls.append("Poster")
        return web.Response(body=b"JPEG" + request.match_info["id"].encode(), content_type="image/jpeg")

    async def _episodes(self, request: web.Request) -> web.Response:
        self.calls.append("Episodes")
        season, season_id = request.query.get("season"), request.query.get("seasonId")
        if season_id is not None:  # the card asks by the season's id
            return web.json_response({"Items": EPISODES if season_id in ("", "se1") else []})
        items = EPISODES if season in (None, "", "1") else []
        return web.json_response({"Items": items})

    async def _seasons(self, request: web.Request) -> web.Response:
        self.calls.append("Seasons")
        return web.json_response(
            {"Items": [{"Id": "se1", "Name": "Season 1", "IndexNumber": 1}, {"Id": "se2", "Name": "Season 2", "IndexNumber": 2}]}
        )

    async def _sessions(self, request: web.Request) -> web.Response:
        self.calls.append("Sessions")
        out = [
            {
                "Id": "phone",
                "Client": "Jellyfin Android",
                "DeviceName": "Pixel",
                "RemoteEndPoint": "192.168.2.50:51000",
                "SupportsRemoteControl": True,
            }
        ]
        if self.app_open:
            out.append(
                {
                    "Id": "tv",
                    "Client": "Jellyfin webOS",
                    "DeviceName": "65UP77006LB",
                    "RemoteEndPoint": "127.0.0.1:52000",
                    "SupportsRemoteControl": True,
                }
            )
        return web.json_response(out)

    async def _playing(self, request: web.Request) -> web.Response:
        self.calls.append("Playing")
        self.played.append((request.match_info["id"], request.query.get("itemIds", ""), int(request.query.get("startPositionTicks") or 0)))
        return web.Response(status=204)
