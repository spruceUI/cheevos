import json
import sqlite3

import pytest

from cheevos.core import proxy
from cheevos.core.proxy import ProxyReader


class StreamingCursor(sqlite3.Cursor):
    def fetchall(self):
        raise AssertionError("Metadata bodies must be streamed")

    def __next__(self):
        row = super().__next__()
        assert isinstance(self.connection, StreamingConnection)
        self.connection.read_keys.append(row[0])
        return row

    def close(self):
        assert isinstance(self.connection, StreamingConnection)
        self.connection.closed_queries += 1
        super().close()


class StreamingConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read_keys = []
        self.closed_queries = 0

    def execute(self, *args, **kwargs):
        return self.cursor(factory=StreamingCursor).execute(*args, **kwargs)


@pytest.fixture(params=[False, True], ids=["minimal-old-schema", "current-schema"])
def db(request):
    connection = sqlite3.connect(":memory:", factory=StreamingConnection)
    columns = "cacheKey TEXT PRIMARY KEY, responseBody TEXT"
    if request.param:
        columns = (
            "id INTEGER PRIMARY KEY, cacheKey TEXT NOT NULL UNIQUE, responseBody TEXT NOT NULL, "
            "sourceRomPath TEXT, cachedAt INTEGER NOT NULL DEFAULT 0, "
            "firstCachedAt INTEGER NOT NULL DEFAULT 0"
        )
    connection.executescript(f"CREATE TABLE api_cache ({columns});")
    yield connection
    connection.close()


def cache(db, key, achievements, *, title="Game"):
    data = {"Title": title, "Achievements": achievements}
    body = {"GameId": 3830, **data} if key.startswith("achievementsets:") else {"PatchData": data}
    db.execute(
        "INSERT INTO api_cache (cacheKey, responseBody) VALUES (?, ?)",
        (key, json.dumps(body)),
    )
    db.closed_queries = 0


def test_streams_and_stops_before_unneeded_patches_or_other_accounts(db):
    cache(db, "patch:900000:balah", [{"ID": 70, "Title": "Own", "Points": 5}])
    cache(db, "patch:900000:another", [{"ID": 70, "Title": "Other", "Points": 1}])
    cache(db, "achievementsets:hash:balah", [{"ID": 70, "Title": "Sets"}])
    db.executemany(
        "INSERT INTO api_cache (cacheKey, responseBody) VALUES (?, ?)",
        (
            (f"patch:{game_id}:balah", json.dumps({"PatchData": {"Achievements": []}}))
            for game_id in range(900001, 901001)
        ),
    )

    entries = ProxyReader._patch_index(db, " BALAH ", {70})

    assert entries[70].achievement_title == "Own"
    assert db.read_keys == ["patch:900000:balah"]
    assert db.closed_queries == 1


def test_own_metadata_wins_and_other_accounts_only_fill_unresolved_ids(db):
    cache(db, "patch:900000:another", [{"ID": 70, "Title": "Stale"}])
    cache(db, "patch:900000:balah", [{"ID": 70, "Title": "Own"}])
    cache(db, "patch:900001:another", [{"ID": 71, "Title": "Fallback"}])
    # LIKE would treat the underscore in this username as a wildcard.
    cache(db, "patch:900002:b_lah", [{"ID": 70, "Title": "Different account"}])
    cache(db, "patch:900003:another", [{"ID": 72, "Title": "Unneeded"}])

    wanted = {70, 71}
    entries = ProxyReader._patch_index(db, "balah", wanted)

    assert set(entries) == wanted
    assert wanted == {70, 71}
    assert entries[70].achievement_title == "Own"
    assert entries[71].achievement_title == "Fallback"
    assert db.read_keys == [
        "patch:900000:balah",
        "patch:900000:another",
        "patch:900001:another",
    ]
    assert db.closed_queries == 2


@pytest.mark.parametrize("prefix", ["patch:90000", "achievementsets:hash"])
def test_account_suffix_is_literal_and_parameterized(db, prefix):
    username = "b_%' or 1=1 --"
    cache(db, prefix + "0:someone", [{"ID": 70, "Title": "Other"}])
    cache(db, prefix + "1:" + username, [{"ID": 70, "Title": "Own"}])

    entries = ProxyReader._patch_index(db, username.upper(), {70})

    assert entries[70].achievement_title == "Own"
    assert db.read_keys == [prefix + "1:" + username]


def test_malformed_own_patches_do_not_prevent_fallback_or_unknown_ids(db):
    db.executemany(
        "INSERT INTO api_cache (cacheKey, responseBody) VALUES (?, ?)",
        [
            ("patch:900000:balah", "{invalid"),
            ("patch:900001:balah", json.dumps({"PatchData": None})),
            ("patch:900002:balah", b"not text"),
            ("patch:junk:balah", "{}"),
            ("gameid:abc", "{}"),
        ],
    )
    cache(db, "patch:900000:another", [{"ID": 70, "Title": "Fallback"}])
    entries = ProxyReader._patch_index(db, "balah", {70, 999})

    assert set(entries) == {70}
    assert entries[70].achievement_title == "Fallback"
    assert "gameid:abc" not in db.read_keys
    assert db.closed_queries == 4  # unknown IDs reach both account passes for each format


def test_empty_lookup_does_not_read_metadata(db):
    cache(db, "patch:900000:balah", [{"ID": 70}])
    assert ProxyReader._patch_index(db, "balah", set()) == {}
    assert db.read_keys == []
    assert db.closed_queries == 0


@pytest.mark.parametrize("keyed", [False, True], ids=["list", "dictionary"])
def test_patch_allocates_metadata_only_for_queued_ids(monkeypatch, keyed):
    achievements = [{"ID": aid, "Title": f"Achievement {aid}"} for aid in range(1000)]
    if keyed:
        achievements = {str(a["ID"]): a for a in achievements}
    body = json.dumps({"PatchData": {"Achievements": achievements}})
    allocated = []
    real_info = proxy._PatchInfo

    def record_info(**kwargs):
        info = real_info(**kwargs)
        allocated.append(info)
        return info

    monkeypatch.setattr(proxy, "_PatchInfo", record_info)
    entries = proxy._patch_entries(7, body, {70, 4000})

    assert set(entries) == {70}
    assert allocated == [entries[70]]


def test_streams_sets_after_both_patch_passes_and_stops_before_unneeded_bodies(db):
    cache(db, "patch:900000:another", [{"ID": 70, "Title": "Patch"}])
    cache(db, "achievementsets:0000:another", [{"ID": 70}, {"ID": 71}, {"ID": 72}])
    cache(db, "achievementsets:0000:balah", [{"ID": 70}, {"ID": 71, "Title": "Own"}])
    db.executemany(
        "INSERT INTO api_cache (cacheKey, responseBody) VALUES (?, ?)",
        (
            (f"achievementsets:{index:04d}:another", json.dumps({"GameId": 7, "Achievements": []}))
            for index in range(1, 1001)
        ),
    )

    entries = ProxyReader._patch_index(db, "balah", {70, 71, 72})

    assert entries[70].achievement_title == "Patch"
    assert entries[71].achievement_title == "Own"
    assert set(entries) == {70, 71, 72}
    assert db.read_keys == [
        "patch:900000:another",
        "achievementsets:0000:balah",
        "achievementsets:0000:another",
    ]
    assert db.closed_queries == 4


def test_sets_stop_before_other_accounts_when_own_metadata_resolves_queue(db):
    cache(db, "achievementsets:hash:another", [{"ID": 70}])
    cache(db, "achievementsets:hash:balah", [{"ID": 70, "Title": "Own"}])

    entries = ProxyReader._patch_index(db, "balah", {70})

    assert entries[70].achievement_title == "Own"
    assert db.read_keys == ["achievementsets:hash:balah"]
    assert db.closed_queries == 3


@pytest.mark.parametrize("keyed", [False, True], ids=["list", "dictionary"])
@pytest.mark.parametrize("nested", [False, True], ids=["direct", "nested"])
def test_sets_allocates_metadata_only_for_queued_ids(monkeypatch, keyed, nested):
    achievements = [{"ID": aid, "Title": f"Achievement {aid}"} for aid in range(1000)]
    if keyed:
        achievements = {str(a["ID"]): a for a in achievements}
    collection = {"Achievements": achievements}
    body = json.dumps({"GameId": 7, **({"Sets": [collection]} if nested else collection)})
    allocated = []
    real_info = proxy._PatchInfo

    def record_info(**kwargs):
        info = real_info(**kwargs)
        allocated.append(info)
        return info

    monkeypatch.setattr(proxy, "_PatchInfo", record_info)
    entries = proxy._achievementsets_entries(body, {70, 4000})

    assert set(entries) == {70}
    assert allocated == [entries[70]]
