"""Bring PyUI up on its ``DESKTOP`` device, as PyUI's launcher would before opening the app.

On a handheld PyUI is already running when it opens Cheevos (:mod:`cheevos.native`). The desktop
runner has no launcher, so it mirrors the start-up order of PyUI's ``mainui.py`` (config,
device, state, theme, display, controller) without the launcher's own parts: menu loops,
background services, theme conversion and the stdout/stderr redirection of ``PyUiLogger.init``.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEVICE = "DESKTOP"


@dataclass(frozen=True, slots=True)
class PyUiSetup:
    """Everything needed to bring PyUI up.

    Attributes:
        main_ui_dir: PyUI's ``main-ui`` directory (contains ``mainui.py``).
        config_path: PyUI config JSON; its ``themeDir`` key locates the themes directory.
        state_path: Where PyUI keeps its view state (last selections).
        theme: Theme folder name inside ``themeDir``, e.g. ``"SPRUCE"``.
        user_config_path: PyUI's ``pyui-common.json``, which PyUI hard-codes to the SD card.
    """

    main_ui_dir: Path
    config_path: Path
    state_path: Path
    theme: str
    user_config_path: Path


def add_pyui_to_path(main_ui_dir: Path) -> None:
    """Make PyUI's top-level packages importable.

    PyUI must sit at ``sys.path[0]``: its ``Language`` class finds the ``lang`` directory
    relative to ``sys.path[0]``.

    Args:
        main_ui_dir: PyUI's ``main-ui`` directory.

    Raises:
        FileNotFoundError: If ``main_ui_dir`` does not contain ``mainui.py``.
    """
    if not (main_ui_dir / "mainui.py").is_file():
        raise FileNotFoundError(f"PyUI not found at {main_ui_dir}")
    entry = str(main_ui_dir)
    if entry in sys.path:
        sys.path.remove(entry)
    sys.path.insert(0, entry)


def install_logger(pyui_logger: logging.Logger) -> None:
    """Route PyUI's logging into ``pyui_logger`` instead of calling ``PyUiLogger.init``.

    ``PyUiLogger.init`` replaces ``sys.stdout``/``sys.stderr`` and adds its own handlers;
    every PyUI module only ever calls ``PyUiLogger.get_logger()``, so injecting the cached
    logger is enough.

    Args:
        pyui_logger: Logger that receives all PyUI log records.
    """
    from utils.logger import PyUiLogger

    # Private attribute, but it is PyUI's only logger handle; see the docstring.
    PyUiLogger._logger = pyui_logger


def start(setup: PyUiSetup) -> None:
    """Initialise PyUI's config, device, theme, display and controller.

    Call :func:`add_pyui_to_path` and :func:`install_logger` first. The ``DESKTOP`` device is
    configured by the ``PYUI_DESKTOP_*`` variables.

    Args:
        setup: Paths and theme to use.
    """
    from controller.controller import Controller
    from devices.device import Device
    from devices.device_factory import initialize_device
    from devices.miyoo.user_config import UserConfig
    from display.display import Display
    from menus.language.language import Language
    from themes.theme import Theme
    from utils.cfw_system_config import CfwSystemConfig
    from utils.py_ui_config import PyUiConfig
    from utils.py_ui_state import PyUiState

    PyUiConfig.init(str(setup.config_path))
    UserConfig.FILEPATH = str(setup.user_config_path)
    UserConfig.reload_config()
    CfwSystemConfig.init(None)
    Language.init()

    initialize_device(DEVICE, main_ui_mode=False)
    device = Device.get_device()
    device.restore_saved_timezone()
    setup.state_path.parent.mkdir(parents=True, exist_ok=True)
    if not setup.state_path.exists():
        setup.state_path.write_text("{}", encoding="utf-8")
    PyUiState.init(str(setup.state_path))

    theme_dir = Path(PyUiConfig.get("themeDir")) / setup.theme
    logger.info("PyUI theme %s at %dx%d", theme_dir, device.screen_width(), device.screen_height())
    Theme.init(str(theme_dir), device.screen_width(), device.screen_height())
    Display.init()
    Display.present()
    Controller.init()
