import os
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from cheevos.ui.pyui.bootstrap import _warm_wifi_status, pyui_device

REPO = Path(__file__).resolve().parents[2]
PYUI_DIR = Path(os.environ.get("CHEEVOS_PYUI_DIR", REPO / ".spruceos/App/PyUI/main-ui"))


@pytest.fixture
def device_modules(monkeypatch):
    device = SimpleNamespace()
    holder = SimpleNamespace(get_device=Mock(return_value=device))
    package = ModuleType("devices")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "devices", package)
    monkeypatch.setitem(sys.modules, "devices.device", SimpleNamespace(Device=holder))
    factory = Mock()
    monkeypatch.setitem(
        sys.modules, "devices.device_factory", SimpleNamespace(initialize_device=factory)
    )
    backlight = Mock()
    monkeypatch.setattr("cheevos.ui.pyui.bootstrap._enable_backlight_control", backlight)
    return SimpleNamespace(device=device, factory=factory, backlight=backlight)


@pytest.mark.parametrize("name", ["MIYOO_MINI_PLUS", "TRIMUI_BRICK", "DESKTOP"])
def test_device_uses_upstream_factory(name, device_modules):
    assert pyui_device(name) is device_modules.device
    device_modules.factory.assert_called_once_with(name, main_ui_mode=False)
    device_modules.backlight.assert_called_once_with(device_modules.device)


def test_device_does_not_hide_factory_initialization_errors(device_modules):
    device_modules.factory.side_effect = ModuleNotFoundError("broken device", name="sdl2")
    with pytest.raises(ModuleNotFoundError, match="broken device"):
        pyui_device("MIYOO_MINI_PLUS")


@pytest.mark.skipif(
    not (PYUI_DIR / "devices/device_factory.py").is_file(), reason="no PyUI checkout"
)
def test_upstream_device_imports_leave_launcher_and_game_menus_unloaded():
    probe = """
import devices.device_factory
import devices.miyoo.mini.miyoo_mini_common
import devices.trimui.trim_ui_brick
import sys
for name in ('mainui', 'menus.main_menu', 'menus.games.game_system_select_menu',
             'menus.games.utils.rom_select_options_builder'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=PYUI_DIR,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_wifi_status_is_read_ahead_on_a_thread():
    read = threading.Event()
    main = threading.current_thread()
    threads = []

    def get_wifi_status():
        threads.append(threading.current_thread())
        read.set()

    _warm_wifi_status(SimpleNamespace(get_wifi_status=get_wifi_status))
    assert read.wait(5)
    assert threads[0] is not main


def test_a_failed_wifi_read_does_not_escape():
    failed = threading.Event()

    def get_wifi_status():
        failed.set()
        raise RuntimeError("wifiCmd missing")

    _warm_wifi_status(SimpleNamespace(get_wifi_status=get_wifi_status))
    assert failed.wait(5)
