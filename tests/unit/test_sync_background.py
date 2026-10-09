import threading
from pathlib import Path

from cheevos.core.errors import CheevosError
from cheevos.core.ra_client.client import RaClient
from cheevos.core.ra_client.transport import FixtureTransport
from cheevos.core.storage.data_cache import DataCache
from cheevos.core.storage.media_cache import MediaCache
from cheevos.core.sync.background import BackgroundSync
from cheevos.core.sync.engine import SyncDeps, SyncOptions
from cheevos.core.sync.progress import Failure, Phase

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ra"


def test_background_sync_runs_on_a_worker_and_closes(tmp_path):
    closed = threading.Event()
    transport = FixtureTransport(FIXTURES)

    def open_deps(_cancel):
        client = RaClient("Balah", "k" * 32, transport, user_agent="test", min_interval=0)
        data = DataCache.open(tmp_path / "data.db", "Balah")
        media = MediaCache.open(tmp_path / "media.db", tmp_path / "scratch")

        def close():
            data.close()
            media.close()
            closed.set()

        return SyncDeps(client, data, media, close=close)

    sync = BackgroundSync(open_deps, online=lambda: True)
    assert sync.start(SyncOptions())
    sync.join(timeout=30)
    assert sync.status().phase is Phase.DONE
    assert closed.is_set()
    assert not sync.status().running


def test_background_sync_reports_open_failure(tmp_path):
    def open_deps(_cancel):
        raise CheevosError("no key")

    sync = BackgroundSync(open_deps, online=lambda: True)
    sync.start(SyncOptions())
    sync.join(timeout=5)
    assert sync.status().failure is Failure.ERROR


def test_background_sync_refuses_a_second_concurrent_start(tmp_path):
    release = threading.Event()

    def open_deps(_cancel):
        release.wait(5)
        raise CheevosError("stop")

    sync = BackgroundSync(open_deps, online=lambda: True)
    assert sync.start(SyncOptions())
    assert sync.status().running
    assert not sync.start(SyncOptions())
    sync.cancel()
    release.set()
    sync.join(timeout=5)


def test_background_sync_hands_each_run_its_cancel_event(tmp_path):
    seen = []

    def open_deps(cancel):
        seen.append(cancel)
        raise CheevosError("stop")

    sync = BackgroundSync(open_deps, online=lambda: True)
    sync.start(SyncOptions())
    sync.join(timeout=5)
    sync.cancel()
    assert seen
    assert seen[0].is_set()
