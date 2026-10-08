from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Event:
    """A marketplace event normalized across providers."""

    provider: str
    provider_event_id: str
    title: str
    starts_at: datetime  # tz-aware when the provider gives an offset, else naive local time
    venue_id: str | None
    venue_name: str
    city: str
    url: str
    lowest_price: float | None  # None = no tickets listed / price unknown
    currency: str = "USD"
    performers: tuple[str, ...] = field(default_factory=tuple)
    # (performer name, home venue id) pairs, when the provider exposes them.
    home_venues: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass
class Watch:
    """Criteria to match events against. One watch spans many games and providers."""

    id: int | None
    query: str  # team / performer name, free text
    target_price: float
    date_from: date | None = None
    date_to: date | None = None
    quantity: int = 1
    home_only: bool = False
    venue_name: str | None = None  # substring match, case-insensitive
    active: bool = True
