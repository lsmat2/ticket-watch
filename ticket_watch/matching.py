from __future__ import annotations

import re
from datetime import datetime

from ticket_watch.models import Event, Watch

# "Away at Home" (SeatGeek, most US sports) vs "Home vs Away" (StubHub style).
_AT = re.compile(r"\s+at\s+", re.IGNORECASE)
_VS = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)


def _mentions(text: str, query: str) -> bool:
    return query.strip().lower() in text.lower()


def game_key(event: Event) -> tuple[datetime, str]:
    """Identifies the same real-world game across providers: local start minute + city.

    Start time alone isn't enough (e.g. the Knicks and their G-League affiliate can tip off at 7pm
    the same night). City is more consistent across providers than venue names.
    """
    return event.starts_at.replace(tzinfo=None, second=0, microsecond=0), event.city.strip().lower()


def is_home_game(event: Event, query: str) -> bool:
    """Best-effort home-game check. Unknown counts as not home, so we never alert on away games."""
    for performer, home_venue_id in event.home_venues:
        if _mentions(performer, query):
            return event.venue_id == home_venue_id

    if len(parts := _AT.split(event.title, maxsplit=1)) == 2:
        return _mentions(parts[1], query)
    if len(parts := _VS.split(event.title, maxsplit=1)) == 2:
        return _mentions(parts[0], query)
    return False


def matches(watch: Watch, event: Event) -> bool:
    """Filters a provider search can't express. Query and date range are applied by the provider."""
    if watch.venue_name and not _mentions(event.venue_name, watch.venue_name):
        return False
    if watch.home_only and not is_home_game(event, watch.query):
        return False
    return True
