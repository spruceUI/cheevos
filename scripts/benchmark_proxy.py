"""Measure pending-award reads against a large disposable proxy cache (dev only).

Run each lookup in a fresh process to measure elapsed time and peak RSS independently of
cache generation. Optionally compare with an older ``core/proxy.py`` saved to ``--baseline``.
The temporary card is synthetic; no installed proxy or user data is read or changed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import resource
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cheevos.core.errors import ConfigError
from cheevos.core.proxy import ProxyReader
from cheevos.platform.paths import Paths

FIRST_GAME = 900_000
OTHER_GAME = 800_000
USERNAME = "benchmark"
DDL = """
CREATE TABLE api_cache (
    id INTEGER PRIMARY KEY, cacheKey TEXT NOT NULL UNIQUE, responseBody TEXT NOT NULL,
    sourceRomPath TEXT, cachedAt INTEGER NOT NULL, firstCachedAt INTEGER NOT NULL
);
CREATE TABLE pending_awards (
    id INTEGER PRIMARY KEY, achievementId INTEGER NOT NULL UNIQUE,
    queuedAt INTEGER NOT NULL, status TEXT NOT NULL
);
"""


def _patch(game_id: int, per_game: int) -> str:
    """Build a response with unique achievements and realistic unused patch fields."""
    return json.dumps(
        {
            "Success": True,
            "PatchData": {
                "ID": game_id,
                "Title": f"Game {game_id}",
                "Achievements": [
                    {
                        "ID": game_id * per_game + index,
                        "Title": f"Achievement {index}",
                        "Description": "Do something memorable in this synthetic game.",
                        "Points": 5,
                        "MemAddr": "0xH000000=1_" * 24,
                    }
                    for index in range(per_game)
                ],
            },
        }
    )


def _build(paths: Paths, games: int, per_game: int) -> None:
    """Write one patch per game plus another account's fallback into a temporary card."""
    paths.proxy_data_dir.mkdir(parents=True)
    with sqlite3.connect(paths.proxy_data_dir / "proxy.sqlite3") as connection:
        connection.executescript(DDL)
        connection.executemany(
            "INSERT INTO api_cache (cacheKey, responseBody, cachedAt, firstCachedAt) "
            "VALUES (?, ?, 0, 0)",
            (
                (f"patch:{game_id}:{USERNAME}", _patch(game_id, per_game))
                for game_id in range(FIRST_GAME, FIRST_GAME + games)
            ),
        )
        connection.execute(
            "INSERT INTO api_cache (cacheKey, responseBody, cachedAt, firstCachedAt) "
            "VALUES (?, ?, 0, 0)",
            (f"patch:{OTHER_GAME}:another", _patch(OTHER_GAME, per_game)),
        )
    connection.close()


def _queue(paths: Paths, achievement_ids: list[int]) -> None:
    """Replace only the synthetic queue between benchmark scenarios."""
    with sqlite3.connect(paths.proxy_data_dir / "proxy.sqlite3") as connection:
        connection.execute("DELETE FROM pending_awards")
        connection.executemany(
            "INSERT INTO pending_awards (achievementId, queuedAt, status) "
            "VALUES (?, 1000, 'pending')",
            ((achievement_id,) for achievement_id in achievement_ids),
        )
    connection.close()


def _reader(source: Path | None) -> Any:  # noqa: ANN401 — optional historical module is untyped
    """Load the current reader, or a saved historical module in the measurement process."""
    if source is None:
        return ProxyReader
    name = "cheevos_proxy_benchmark_baseline"
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ConfigError(f"Cannot load baseline reader from {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve the historical module by name
    spec.loader.exec_module(module)
    return module.ProxyReader


def _measure(card: Path, source: Path | None) -> dict[str, Any]:
    """Measure one read, including the process's total peak RSS and returned queue data."""
    reader = _reader(source)(Paths(sdcard=card))
    started = time.perf_counter()
    awards = reader.pending_awards(USERNAME)
    elapsed = time.perf_counter() - started
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return {
        "elapsed_seconds": elapsed,
        "peak_rss_mib": peak_rss / rss_divisor,
        "awards": [asdict(award) for award in awards],
    }


def _samples(card: Path, source: Path | None, repeats: int) -> list[dict[str, Any]]:
    """Collect independent reads in fresh child processes."""
    command = [sys.executable, str(Path(__file__).resolve()), "--measure", str(card)]
    if source is not None:
        command.extend(["--baseline", str(source.resolve())])
    return [
        json.loads(subprocess.check_output(command, text=True))  # noqa: S603 — local benchmark worker
        for _ in range(repeats)
    ]


def _expected(achievement_ids: list[int], per_game: int, *, missing: bool) -> list[dict[str, Any]]:
    """Describe expected queue metadata independently of either lookup implementation."""
    return [
        {
            "achievement_id": aid,
            "game_id": None if missing else aid // per_game,
            "game_title": "" if missing else f"Game {aid // per_game}",
            "achievement_title": "" if missing else f"Achievement {aid % per_game}",
            "points": None if missing else 5,
            "queued_at": 1,
        }
        for aid in achievement_ids
    ]


def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    """Generate a temporary cache and compare small queues at several lookup positions."""
    readers = {"current": None}
    if args.baseline is not None:
        readers = {"baseline": args.baseline, **readers}
    scenarios = {
        "early": FIRST_GAME,
        "late": FIRST_GAME + args.games - 1,
        "other_account": OTHER_GAME,
        "missing": FIRST_GAME + args.games,
    }
    report: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "games": args.games + 1,
        "achievements_per_game": args.per_game,
        "queue_size": 2,
        "repeats": args.repeats,
        "results": {},
    }
    with tempfile.TemporaryDirectory(prefix="cheevos-proxy-benchmark-") as directory:
        paths = Paths(sdcard=Path(directory))
        _build(paths, args.games, args.per_game)
        report["cache_mib"] = (paths.proxy_data_dir / "proxy.sqlite3").stat().st_size / (
            1024 * 1024
        )
        for scenario, game_id in scenarios.items():
            achievement_ids = [game_id * args.per_game, game_id * args.per_game + 1]
            _queue(paths, achievement_ids)
            expected = _expected(achievement_ids, args.per_game, missing=scenario == "missing")
            report["results"][scenario] = {}
            for name, source in readers.items():
                samples = _samples(paths.sdcard, source, args.repeats)
                if any(sample["awards"] != expected for sample in samples):
                    raise ConfigError(f"{name} returned incorrect metadata for {scenario}")
                report["results"][scenario][name] = {
                    "median_seconds": statistics.median(s["elapsed_seconds"] for s in samples),
                    "max_peak_rss_mib": max(s["peak_rss_mib"] for s in samples),
                }
    return report


def main() -> int:
    """Parse benchmark options and print a JSON report, or measure one child-process read."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--games", type=int, default=2000)
    parser.add_argument("--per-game", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--measure", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.games < 1 or args.per_game < 2 or args.repeats < 1:  # noqa: PLR2004 — queue has two IDs
        parser.error("games and repeats must be positive; per-game must be at least two")
    result = _measure(args.measure, args.baseline) if args.measure is not None else benchmark(args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
