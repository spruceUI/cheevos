import datetime as dt
import logging
import sys
import time
from types import SimpleNamespace

import pytest

from cheevos.platform.desktop.__main__ import _fix_top_bar_clock, parse_options


def test_clock_is_parsed_as_a_time_of_day():
    assert parse_options(["--clock", "10:30"]).clock == dt.time(10, 30)
    assert parse_options([]).clock is None


def test_clock_must_be_a_time(capsys):
    with pytest.raises(SystemExit):
        parse_options(["--clock", "half past ten"])
    assert "expected HH:MM" in capsys.readouterr().err


def test_fixed_clock_replaces_the_time_pyui_reads(monkeypatch):
    top_bar = SimpleNamespace(datetime=dt.datetime)
    monkeypatch.setitem(sys.modules, "menus.common", SimpleNamespace(top_bar=top_bar))
    _fix_top_bar_clock(dt.time(10, 30))
    # As TopBar.get_current_time_hhmm() reads it, and still formatted by PyUI.
    assert top_bar.datetime.fromtimestamp(time.time()).strftime("%I:%M %p") == "10:30 AM"
    assert top_bar.datetime.now().strftime("%H:%M") == "10:30"


def test_fixed_clock_warns_when_pyui_reads_the_time_another_way(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "menus.common", SimpleNamespace(top_bar=SimpleNamespace()))
    with caplog.at_level(logging.WARNING):
        _fix_top_bar_clock(dt.time(10, 30))
    assert "--clock has no effect" in caplog.text
