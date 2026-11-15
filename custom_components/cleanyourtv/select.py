"""Carry on watching: pick a series or film from the Jellyfin server and the TV starts it, where you stopped.

The entity is there as soon as a Jellyfin server is set up in the options; there is nothing to write in YAML. Picking an option
turns the TV on if it has to, opens a Jellyfin client and plays. Its attributes carry the whole list, so a dashboard can show more
than the names.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CytvConfigEntry
from .const import CONF_JF_KEY, CONF_JF_URL, DOMAIN
from .entity import CytvEntity
from .library import SIGNAL_LIBRARY, label


async def async_setup_entry(hass: HomeAssistant, entry: CytvConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([CytvContinueSelect(entry)])


class CytvContinueSelect(CytvEntity, SelectEntity):
    _attr_translation_key = "continue_watching"
    _unrecorded_attributes = frozenset({"series", "movies", "items"})

    def __init__(self, entry: CytvConfigEntry) -> None:
        super().__init__(entry, "continue_watching")

    @property
    def available(self) -> bool:
        """There is something to pick as long as a server is set up; the TV itself may be off, it is turned on when you pick."""
        o = self._entry.options
        return bool(o.get(CONF_JF_URL) and o.get(CONF_JF_KEY))

    @property
    def options(self) -> list[str]:
        return [label(r) for r in self._rows]

    @property
    def current_option(self) -> str | None:
        """Nothing is "chosen": the list is a way to start something, so it stays empty and the same title can be picked again."""
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        lib = self._data.library
        return {
            "series": self._data.library.series if lib else [],
            "movies": self._data.library.movies if lib else [],
            "items": self._rows,
        }

    @property
    def _rows(self) -> list[dict[str, Any]]:
        lib = self._data.library
        return lib.rows if lib else []

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _changed() -> None:
            self.async_write_ha_state()

        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_LIBRARY.format(self._entry.entry_id), _changed))

    async def async_select_option(self, option: str) -> None:
        from .play import async_play

        row = next((r for r in self._rows if label(r) == option), None)
        if row is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_found", translation_placeholders={"title": option})
        await async_play(self.hass, self._entry, item_id=row["id"])
        if self._data.library:
            self._data.library.refresh_soon()
