"""Open and close Cheevos twice in one PyUI process, as Spruce's menus do, then unload it.

Run by ``test_native_sessions.py`` in a subprocess. PyUI comes up on its desktop device first,
as its launcher would; the script drives both sessions. Afterwards the app's modules are dropped
the way PyUI drops them (``App/PyUI/main-ui/apps/native_app.py``), and the report on stdout
lists whatever of Cheevos is still alive, running or hooked into PyUI.

Usage: ``python native_session.py <sd root> <shots dir> <script for both sessions> [game ID]``
(with a game ID, the second session opens that game only, as Spruce's game menu does).
"""

import dataclasses
import gc
import json
import logging
import sys
import threading
import time
import weakref
from pathlib import Path

APP = "cheevos"


def sessions(sd_root: Path, out_dir: Path, script: str, game_id: int | None) -> list[str]:
    from cheevos import native
    from cheevos.platform.desktop.__main__ import parse_options, start_pyui
    from cheevos.platform.desktop.environments import fixture_environment

    options = parse_options(["--headless", "--script", script, "--out", str(out_dir)])
    options = dataclasses.replace(options, sd_root=sd_root)
    if problem := start_pyui(options):
        raise SystemExit(problem)
    for target in (None, game_id):
        native.session(fixture_environment(sd_root), started_at=time.monotonic(), game_id=target)
    from devices.device import Device

    return [str(step) for step in Device.get_device().get_controller_interface().unplayed]


def unload() -> list[weakref.ref]:
    names = [name for name in sys.modules if name == APP or name.startswith(APP + ".")]
    modules = [weakref.ref(sys.modules.pop(name)) for name in names]
    gc.collect()
    return modules


def leftovers(modules: list[weakref.ref]) -> dict[str, list[str]]:
    from display.display import Display
    from themes.theme import Theme
    from views.list_view import ListView

    def from_app(thing: object) -> bool:
        return str(getattr(thing, "__module__", "") or "").split(".")[0] == APP

    alive = [module.__name__ for module in (ref() for ref in modules) if module is not None]
    objects = sorted(
        {
            f"{type(obj).__module__}.{type(obj).__qualname__}"
            for obj in gc.get_objects()
            if from_app(type(obj)) or (callable(obj) and from_app(obj))
        }
    )
    hooks = []
    for name in ("_text_texture_cache", "_image_texture_cache"):
        if type(getattr(Display, name).cache) is not dict:
            hooks.append(f"Display.{name}")
    if "render_bottom_bar" in vars(Display.bottom_bar):
        hooks.append("Display.bottom_bar.render_bottom_bar")
    if "render_top_bar" in vars(Display.top_bar):
        hooks.append("Display.top_bar.render_top_bar")
    if logging.getLogRecordFactory() is not logging.LogRecord:
        hooks.append("logging record factory")
    for owner, attribute in ((Theme, "keyboard_entry_bg"), (ListView, "_calculate_line_height")):
        if from_app(vars(owner)[attribute]):
            hooks.append(f"{owner.__name__}.{attribute}")
    app_logger = logging.getLogger(APP)
    if app_logger.handlers:
        hooks.append(f"handlers on the {APP!r} logger")
    threads = [t.name for t in threading.enumerate() if t.name.startswith(APP + "-")]
    return {"modules": alive, "objects": objects, "hooks": hooks, "threads": threads}


def main() -> None:
    sd_root, out_dir, script = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    game_id = int(sys.argv[4]) if len(sys.argv) > 4 else None
    unplayed = sessions(sd_root, out_dir, script, game_id)
    report = leftovers(unload())
    print(json.dumps({"unplayed": unplayed, **report}))


if __name__ == "__main__":
    main()
