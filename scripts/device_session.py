"""Development only: open Cheevos on a device as PyUI's menus do, without tapping through them.

``scripts/device.sh launch`` copies this to ``/tmp/cheevos-dev/session.py`` on the device, saves
the running PyUI's environment, command line and working directory next to it, then asks PyUI
to exit; ``principal.sh`` runs this with PyUI's own interpreter. It takes PyUI's environment
back, brings PyUI up the way ``mainui.py`` does (minus the menus and background services), and
opens Cheevos with PyUI's ``apps.native_app.run``, the call the Apps menu makes. When Cheevos
closes, so does this, and ``principal.sh`` restarts PyUI.

Never part of the device package. Memory figures taken this way leave out PyUI's menus.

Usage (on the device): ``<PyUI's python> /tmp/cheevos-dev/session.py [--game-id N]``
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path
from types import FrameType

DEV_DIR = Path(__file__).resolve().parent
APP_DIR = Path("/mnt/SDCARD/App/Cheevos")
_PYUI_ENV = "CHEEVOS_DEV_SESSION"  # set once PyUI's environment is in place


def _saved(name: str) -> list[str]:
    """Read a NUL-separated file ``device.sh`` saved from the running PyUI's ``/proc`` entry.

    Args:
        name: ``environ`` or ``cmdline``.

    Returns:
        Its entries.
    """
    return [item.decode() for item in (DEV_DIR / name).read_bytes().split(b"\0") if item]


def _take_pyui_environment() -> None:
    """Restart this interpreter with PyUI's environment, as its library paths need it at exec."""
    if os.environ.get(_PYUI_ENV):
        return
    env = dict(item.split("=", 1) for item in _saved("environ") if "=" in item)
    env[_PYUI_ENV] = "1"
    os.execve(sys.executable, sys.orig_argv, env)  # noqa: S606 — this interpreter, again


def _pyui_options() -> tuple[Path, dict[str, str]]:
    """Find PyUI's ``main-ui`` directory and the options PyUI was started with.

    Returns:
        ``(main-ui directory, {"-device": ..., "-pyUiConfig": ..., ...})``.
    """
    argv = _saved("cmdline")
    script = next(Path(arg) for arg in argv if arg.endswith("mainui.py"))
    rest = argv[argv.index(str(script)) + 1 :]
    return script.parent, dict(zip(rest[::2], rest[1::2], strict=False))


def _start_pyui(main_ui: Path, options: dict[str, str]) -> None:
    """Bring PyUI up as ``mainui.py`` does for its menus, with its log in ``/tmp/cheevos-dev``.

    Args:
        main_ui: PyUI's ``main-ui`` directory.
        options: PyUI's command-line options.
    """
    sys.path.insert(0, str(main_ui))  # PyUI first: Language finds lang/ from sys.path[0]
    from controller.controller import Controller  # PyUI, importable only now
    from devices.device import Device
    from devices.device_factory import initialize_device
    from devices.miyoo.user_config import UserConfig
    from display.display import Display
    from menus.language.language import Language
    from themes.theme import Theme
    from utils.cfw_system_config import CfwSystemConfig
    from utils.logger import PyUiLogger
    from utils.py_ui_config import PyUiConfig
    from utils.py_ui_state import PyUiState

    PyUiLogger.init(str(DEV_DIR), "PyUI")
    PyUiConfig.init(options["-pyUiConfig"])
    UserConfig.reload_config()
    CfwSystemConfig.init(options.get("-cfwConfig"))
    Language.init()
    initialize_device(options["-device"], main_ui_mode=True)
    device = Device.get_device()
    device.restore_saved_timezone()
    PyUiState.init(device.get_state_path())
    theme = Path(PyUiConfig.get("themeDir")) / device.get_system_config().get_theme()
    Theme.init(str(theme), device.screen_width(), device.screen_height())
    Display.init()
    Display.present()
    Controller.init()


def _exit_on_sigterm(_signum: int, _frame: FrameType | None) -> None:
    """Leave through the app's own clean-up when ``device.sh stop`` sends SIGTERM."""
    sys.exit(0)


def main() -> None:
    """Open Cheevos once, as the Apps menu (or, with ``--game-id``, the game menu) does."""
    parser = argparse.ArgumentParser(prog="session.py")
    parser.add_argument("--game-id", type=int)
    args = parser.parse_args()
    _take_pyui_environment()
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    _start_pyui(*_pyui_options())
    from apps import native_app  # PyUI's in-process app runner

    entry = json.loads((APP_DIR / "config.json").read_text(encoding="utf-8"))["pyuiEntry"]
    extra = {} if args.game_id is None else {"game_id": args.game_id}
    native_app.run(str(APP_DIR), entry, **extra)


if __name__ == "__main__":
    main()
