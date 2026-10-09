"""Invent the showcase profile's points history separately from its recorded recent feed."""

from __future__ import annotations

import calendar
import time
from collections.abc import Sequence

_MONTH = 31 * 86_400


def unlocks(
    start: int,
    end: int,
    member_since: str,
    recent: Sequence[tuple[int, int, bool]],
) -> list[dict]:
    """Invent points-history rows for See more, including the first hardcore unlock.

    Args:
        start: Window start (epoch seconds).
        end: Window end (epoch seconds).
        member_since: Showcase player's RA registration date.
        recent: ``(days ago, points, hardcore)`` for each recent unlock.

    Returns:
        Rows, oldest first.
    """
    rows = []
    for index, (days_ago, points, hardcore) in enumerate(recent):
        when = time.gmtime(end - days_ago * 86_400 - 3_600)
        rows.append(
            {
                "Date": time.strftime("%Y-%m-%d %H:%M:%S", when),
                "HardcoreMode": int(hardcore),
                "AchievementID": 900_000 + index,
                "Points": points,
                "GameID": 519,
                "ConsoleName": "Game Boy Advance",
            }
        )
    since = time.strptime(member_since, "%Y-%m-%d %H:%M:%S")
    first = calendar.timegm(since) + 86_400
    if start <= first < end - _MONTH:
        rows.append(
            {
                **rows[0],
                "Date": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(first)),
                "HardcoreMode": 1,
                "AchievementID": 899_999,
            }
        )
    return sorted(rows, key=lambda row: row["Date"])
