"""Simulate a recognised game with no achievement set, using the most recent fixture game."""

from __future__ import annotations

import json
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

from cheevos.core.ra_client.transport import API_HOST, Response, Transport

GAME_ID = 554  # Fire Emblem: The Blazing Blade, already absent from completion progress.
_RECENT_COUNTS = (
    "AchievementsTotal",
    "NumPossibleAchievements",
    "PossibleScore",
    "NumAchieved",
    "ScoreAchieved",
    "NumAchievedHardcore",
    "ScoreAchievedHardcore",
)


class NoSetTransport:
    """Serve the fixtures with Fire Emblem's achievement set and counts removed.

    Args:
        base: Recorded transport.
    """

    def __init__(self, base: Transport) -> None:
        self._base = base

    def get(self, host: str, path: str, headers: dict[str, str]) -> Response:
        """Serve recorded responses, making the most recent game a game without a set."""
        response = self._base.get(host, path, headers)
        if host != API_HOST or response.status != 200:  # noqa: PLR2004 — HTTP OK
            return response
        if "API_GetUserRecentlyPlayedGames" in path:
            body = json.loads(response.body)
            for game in body:
                if int(game["GameID"]) == GAME_ID:
                    game.update(dict.fromkeys(_RECENT_COUNTS, 0))
        elif "API_GetGameInfoAndUserProgress" in path:
            query = parse_qs(urlsplit(path).query)
            if int(query.get("g", ["0"])[0]) != GAME_ID:
                return response
            body = json.loads(response.body)
            body.update(
                Achievements={},
                NumAchievements=0,
                NumAwardedToUser=0,
                NumAwardedToUserHardcore=0,
                UserCompletion="0.00%",
                UserCompletionHardcore="0.00%",
                HighestAwardKind=None,
                HighestAwardDate=None,
            )
        else:
            return response
        return replace(response, body=json.dumps(body).encode())
