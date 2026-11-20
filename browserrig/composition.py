from collections.abc import Iterable

from harnessed import Plugin
from harnessed.errors import PluginConflict


def select_plugins(
    defaults: list[Plugin],
    plugins: Iterable[Plugin],
    without: Iterable[type[Plugin]],
) -> list[Plugin]:
    """Apply BrowserRig's facade overrides before handing a flat list to Harnessed."""
    excluded = tuple(without)
    missing = [
        kind.__name__
        for kind in excluded
        if not any(isinstance(plugin, kind) for plugin in defaults)
    ]
    if missing:
        raise ValueError(f"BrowserRig has no defaults matching: {', '.join(missing)}")

    selected = [plugin for plugin in defaults if not isinstance(plugin, excluded)]
    positions = {
        plugin.slot: index
        for index, plugin in enumerate(selected)
        if plugin.slot is not None
    }
    overrides: dict[str, Plugin] = {}
    for plugin in plugins:
        if not isinstance(plugin, Plugin):
            raise TypeError("Expected a Plugin instance")
        _select_plugin(selected, positions, overrides, plugin)
    return selected


def _select_plugin(
    selected: list[Plugin],
    positions: dict[str, int],
    overrides: dict[str, Plugin],
    plugin: Plugin,
) -> None:
    slot = plugin.slot
    if slot is None:
        selected.append(plugin)
        return
    if slot in overrides:
        raise PluginConflict(
            f"Multiple plugins in slot {slot!r}: {overrides[slot].name}, {plugin.name}"
        )
    overrides[slot] = plugin
    if slot in positions:
        selected[positions[slot]] = plugin
    else:
        selected.append(plugin)
