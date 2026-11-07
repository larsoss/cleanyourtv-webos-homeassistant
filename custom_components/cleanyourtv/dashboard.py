"""Putting the remote card on a dashboard of the user's choice: a new view "TV remote" is added to it; nothing else is touched."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

DEFAULT = "_default"  # the default dashboard's key in the choice (its url_path is None)


def _dashboards(hass: HomeAssistant) -> dict:
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    data = hass.data.get(LOVELACE_DATA)
    return data.dashboards if data else {}


async def storage_dashboards(hass: HomeAssistant) -> dict[str, str]:
    """The dashboards that can be edited here (made in the UI), {key: title}. The default one only when it was taken over already:
    otherwise it is generated, and saving a view to it would replace what it shows."""
    out: dict[str, str] = {}
    for url, dash in _dashboards(hass).items():
        if getattr(dash, "mode", "") != "storage":
            continue
        if url is None:
            info = await dash.async_get_info()
            if info.get("mode") == "auto-gen":
                continue
            out[DEFAULT] = "Overview"
        else:
            out[url] = str((dash.config or {}).get("title") or url)
    return out


async def add_remote_view(hass: HomeAssistant, entry: ConfigEntry, key: str) -> str:
    """Add the view; returns the path to open it. ValueError when the dashboard cannot be changed."""
    from homeassistant.components.lovelace.const import ConfigNotFound

    url = None if key == DEFAULT else key
    dash = _dashboards(hass).get(url)
    if dash is None or getattr(dash, "mode", "") != "storage":
        raise ValueError("not a dashboard made in the UI")
    entity = next(
        (e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id) if e.domain == "media_player"), None
    )
    if entity is None:
        raise ValueError("no media player")
    try:
        config = await dash.async_load(False)
    except ConfigNotFound:
        config = {"views": []}  # a new, empty dashboard
    config = dict(config)
    views = list(config.get("views") or [])
    taken = {v.get("path") for v in views}
    path, n = "tv-remote", 2
    while path in taken:
        path, n = f"tv-remote-{n}", n + 1
    nl = str(hass.config.language or "").startswith("nl")
    views.append(
        {
            "title": "TV-afstandsbediening" if nl else "TV remote",
            "path": path,
            "icon": "mdi:remote-tv",
            "type": "sections",
            "max_columns": 1,
            "sections": [
                {
                    "type": "grid",
                    "cards": [
                        {"type": "media-control", "entity": entity},
                        {"type": "custom:cleanyourtv-remote", "entity": entity, "height": 760, "grid_options": {"columns": "full"}},
                    ],
                }
            ],
        }
    )
    config["views"] = views
    await dash.async_save(config)
    return f"/{url or 'lovelace'}/{path}"
