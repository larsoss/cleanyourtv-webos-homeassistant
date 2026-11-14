"""What there is to carry on watching, kept up to date for the select entity and the remote card.

Jellyfin is asked every few minutes (and right after something was played) for the episode to watch next of every series and for the
films that were started and not finished. The items are turned into rows the card and the select can use without knowing Jellyfin.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .jellyfin import JellyfinAuthError, JellyfinError

if TYPE_CHECKING:
    from . import CytvConfigEntry

_LOGGER = logging.getLogger(__name__)

SIGNAL_LIBRARY = f"{DOMAIN}_library_{{}}"
REFRESH_S = 300
AFTER_PLAY_S = 25  # a play has to have started before the server moves the series on
TICKS_S = 10_000_000


def row(item: dict[str, Any]) -> dict[str, Any]:
    """One item as the card and the select read it: what to show, what to play, and how far it got.

    An episode is shown as its series ("Reacher", "S01E03 - First Dance") and carries the series' own poster, which is the picture
    people recognise; a film is shown with its year.
    """
    data = item.get("UserData") or {}
    done = int(data.get("PlaybackPositionTicks") or 0)
    total = int(item.get("RunTimeTicks") or 0)
    out = {
        "id": str(item.get("Id") or ""),
        "kind": "series" if item.get("Type") == "Episode" else "movie",
        "title": str(item.get("Name") or ""),
        "sub": "",
        "poster": str(item.get("Id") or ""),
        "seconds": done // TICKS_S,
        "minutes_left": max(0, (total - done) // TICKS_S // 60) if total else 0,
        "progress": round(min(100.0, done / total * 100), 1) if total and done else 0.0,
    }
    if out["kind"] == "series":
        season, number = item.get("ParentIndexNumber"), item.get("IndexNumber")
        at = f"S{season:02d}E{number:02d}" if isinstance(season, int) and isinstance(number, int) else ""
        out["title"] = str(item.get("SeriesName") or out["title"])
        out["sub"] = " - ".join(p for p in (at, str(item.get("Name") or "")) if p)
        out["poster"] = str(item.get("SeriesId") or out["id"])
    else:
        out["sub"] = str(item.get("ProductionYear") or "")
    return out


def label(r: dict[str, Any]) -> str:
    """One line for a dropdown: "Reacher - S01E03 - First Dance"."""
    return " - ".join(p for p in (r["title"], r["sub"]) if p)[:255]


class Library:
    """The rows of one TV's Jellyfin server, refreshed in the background."""

    def __init__(self, hass: HomeAssistant, entry: CytvConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self.series: list[dict[str, Any]] = []
        self.movies: list[dict[str, Any]] = []
        self.error = ""
        self.updated: Any = None
        self._task: asyncio.Task | None = None
        self._soon: asyncio.Task | None = None

    @property
    def rows(self) -> list[dict[str, Any]]:
        """Series first, then films: the order the select offers them in."""
        return self.series + self.movies

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = self._entry.async_create_background_task(self._hass, self._run(), "cleanyourtv library")

    def stop(self) -> None:
        for task in (self._task, self._soon):
            if task and not task.done():
                task.cancel()

    @callback
    def refresh_soon(self) -> None:
        """Read it again shortly: what was just played is no longer the episode to watch next."""
        if self._soon and not self._soon.done():
            return
        self._soon = self._entry.async_create_background_task(self._hass, self._after_play(), "cleanyourtv library again")

    async def _after_play(self) -> None:
        await asyncio.sleep(AFTER_PLAY_S)
        await self.async_refresh()

    async def _run(self) -> None:
        while True:
            await self.async_refresh()
            await asyncio.sleep(REFRESH_S)

    async def async_refresh(self) -> None:
        """Ask the server, keep what came back, and tell the entities and the card."""
        from .play import jellyfin_of

        jf = jellyfin_of(self._hass, self._entry)
        if jf is None:
            self.series, self.movies, self.error = [], [], ""
            async_dispatcher_send(self._hass, SIGNAL_LIBRARY.format(self._entry.entry_id))
            return
        try:
            got = await jf.async_continue()
        except JellyfinAuthError as err:
            self.error = str(err)
            _LOGGER.warning("Jellyfin no longer accepts the API key: %s", err)
        except JellyfinError as err:
            self.error = str(err)
            _LOGGER.debug("reading what to carry on with failed: %s", err)
        else:
            self.series = [row(i) for i in got["series"]]
            self.movies = [row(i) for i in got["movies"]]
            self.error = ""
            self.updated = dt_util.utcnow()
        async_dispatcher_send(self._hass, SIGNAL_LIBRARY.format(self._entry.entry_id))
