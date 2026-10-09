import json
import threading
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from cheevos.core.errors import ApiPayloadError, RequestCancelledError
from cheevos.core.models import AchievementType
from cheevos.core.ra_client.client import RaClient
from cheevos.core.ra_client.parse import parse_recent_unlocks, parse_time
from cheevos.core.ra_client.transport import Response
from cheevos.core.storage.data_cache import DataCache
from cheevos.core.storage.recent_feed import FEED_KEY, RecentFeed, RecentFeedCache

DAY = 86_400
NOW = 1_791_158_400


def row(achievement_id, when, *, hardcore=True, game_id=519):
    date = datetime.fromtimestamp(when, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "AchievementID": achievement_id,
        "GameID": game_id,
        "Date": date,
        "HardcoreMode": int(hardcore),
        "Title": f"Achievement {achievement_id}",
        "Description": "Win a race",
        "BadgeName": str(achievement_id),
        "Points": 5,
        "TrueRatio": 10,
        "Type": "win_condition",
        "GameTitle": "Game without a cached set",
        "GameIcon": "/Images/123.png",
        "ConsoleName": "Game Boy Advance",
    }


class HistoryTransport:
    """Model RA's inclusive, oldest-first, capped date-range response."""

    def __init__(self, rows, cap=500):
        self.rows = sorted(rows, key=lambda r: (parse_time(r["Date"]), -r["HardcoreMode"]))
        self.cap = cap
        self.calls = []

    def get(self, host, path, headers):
        query = parse_qs(urlsplit(path).query)
        start, end = int(query["f"][0]), int(query["t"][0])
        self.calls.append((start, end))
        rows = [r for r in self.rows if start <= (parse_time(r["Date"]) or 0) <= end]
        return Response(200, body=json.dumps(rows[: self.cap]).encode())


def client(transport, **kwargs):
    return RaClient("Balah", "k" * 32, transport, user_agent="test", min_interval=0, **kwargs)


def test_capped_windows_find_the_newest_rows_instead_of_the_first_page(monkeypatch):
    monkeypatch.setattr("cheevos.core.ra_client.client.UNLOCK_PAGE", 3)
    transport = HistoryTransport([row(i, NOW + i * DAY) for i in range(1, 11)], cap=3)
    found = []
    entries = client(transport).recent_unlocks(
        NOW, NOW + 10 * DAY, count=4, on_progress=found.append
    )
    assert [e.achievement.achievement_id for e in entries] == [10, 9, 8, 7]
    assert found[-1] == 4
    assert found == sorted(found)
    assert len(transport.calls) > 1


def test_sparse_old_history_is_covered_without_using_the_device_date():
    transport = HistoryTransport([row(1, NOW - 9 * 365 * DAY), row(2, NOW)])
    entries = client(transport).recent_unlocks(NOW - 10 * 365 * DAY, NOW)
    assert [e.achievement.achievement_id for e in entries] == [2, 1]
    assert transport.calls[-1][0] == NOW - 10 * 365 * DAY
    assert all(end <= NOW for _, end in transport.calls)


def test_small_accounts_fetch_the_whole_history_in_one_request():
    transport = HistoryTransport([row(1, NOW - 9 * 365 * DAY), row(2, NOW)])
    entries = client(transport).recent_unlocks(0, NOW, known_unlocks=2)
    assert len(entries) == 2
    assert transport.calls == [(0, NOW)]


def test_mode_duplicates_count_once_and_keep_the_newest_unlock():
    transport = HistoryTransport(
        [row(1, NOW - 1, hardcore=False), row(1, NOW), row(2, NOW), row(2, NOW, hardcore=False)]
    )
    entries = client(transport).recent_unlocks(NOW - 10, NOW, count=2)
    assert [e.achievement.achievement_id for e in entries] == [2, 1]
    assert all(e.achievement.hardcore for e in entries)
    assert all(e.achievement.unlocked_at == NOW for e in entries)


def test_time_boundaries_are_inclusive_and_windows_do_not_skip_rows():
    rows = [row(1, NOW - 7 * DAY), row(2, NOW - 7 * DAY + 1), row(3, NOW)]
    entries = client(HistoryTransport(rows)).recent_unlocks(NOW - 7 * DAY, NOW)
    assert [e.achievement.achievement_id for e in entries] == [3, 2, 1]


def test_a_saturated_single_second_fails_instead_of_claiming_coverage(monkeypatch):
    monkeypatch.setattr("cheevos.core.ra_client.client.UNLOCK_PAGE", 3)
    transport = HistoryTransport([row(i, NOW) for i in range(1, 5)], cap=3)
    with pytest.raises(ApiPayloadError, match="one timestamp"):
        client(transport).recent_unlocks(NOW - DAY, NOW, count=2)


def test_a_request_budget_failure_is_explicit(monkeypatch):
    monkeypatch.setattr("cheevos.core.ra_client.recent.MAX_REQUESTS", 1)
    with pytest.raises(ApiPayloadError, match="request budget"):
        client(HistoryTransport([])).recent_unlocks(0, NOW)


def test_recent_fetch_uses_normal_cancellable_requests():
    cancel = threading.Event()
    cancel.set()
    transport = HistoryTransport([])
    with pytest.raises(RequestCancelledError):
        client(transport, cancel=cancel).recent_unlocks(0, NOW)
    assert transport.calls == []


def test_raw_cap_is_checked_before_ignoring_warning_achievements(monkeypatch):
    monkeypatch.setattr("cheevos.core.ra_client.client.UNLOCK_PAGE", 3)
    rows = [row(101000001, NOW - 2 * DAY), row(1, NOW - DAY), row(2, NOW), row(3, NOW)]
    transport = HistoryTransport(rows, cap=3)
    entries = client(transport).recent_unlocks(NOW - 3 * DAY, NOW, count=2)
    assert [e.achievement.achievement_id for e in entries] == [3, 2]
    assert len(transport.calls) > 1


def test_parse_recent_definitions_and_skip_invalid_rows():
    rows = [row(1, NOW)]
    rows += [dict(row(2, NOW), Date="bad"), row(101000001, NOW), row(3, NOW, game_id=0)]
    (entry,) = parse_recent_unlocks(rows)
    assert entry.achievement.description == "Win a race"
    assert entry.achievement.type is AchievementType.WIN_CONDITION
    assert entry.game_icon == "/Images/123.png"
    with pytest.raises(ApiPayloadError):
        parse_recent_unlocks({})


def test_snapshot_survives_reopen_without_marking_game_details_downloaded(tmp_path):
    path = tmp_path / "data.db"
    data = DataCache.open(path, "Balah")
    entries = tuple(parse_recent_unlocks([row(1, NOW)]))
    feed = RecentFeed(entries, "library-state", NOW)
    RecentFeedCache(data).save(feed)
    data.close()
    data = DataCache.open(path, "Balah")
    assert RecentFeedCache(data).load() == feed
    assert data.recent_unlocks(1) == [entries[0].achievement]
    assert data.game_detail(519) is None
    assert data.unlocked_among([1, 2]) == {1}
    assert data.achievement_games([1, 2]) == {1: 519}
    assert data.recent_unlocks(0) == []
    RecentFeedCache(data).save(replace(feed, entries=()))
    assert data.recent_unlocks(100) == []
    data.close()


@pytest.mark.parametrize(
    "payload", ["{bad", "{}", '{"version": 99}', '{"version":1,"entries":[{}]}']
)
def test_unreadable_feed_is_ignored(tmp_path, payload):
    data = DataCache.open(tmp_path / "data.db", "Balah")
    data.set_meta(FEED_KEY, payload)
    assert RecentFeedCache(data).load() is None
    data.close()
