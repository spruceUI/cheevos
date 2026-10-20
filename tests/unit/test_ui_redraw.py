import sys
from types import SimpleNamespace
from unittest.mock import Mock

from cheevos.ui.pyui.redraw import request_redraw


def test_redraw_uses_the_upstream_notification(monkeypatch):
    redraw = Mock()
    monkeypatch.setitem(
        sys.modules,
        "controller.controller",
        SimpleNamespace(Controller=SimpleNamespace(request_redraw=redraw)),
    )
    request_redraw()
    redraw.assert_called_once_with()


def test_redraw_is_optional_on_older_pyui(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "controller.controller", SimpleNamespace(Controller=SimpleNamespace())
    )
    request_redraw()
