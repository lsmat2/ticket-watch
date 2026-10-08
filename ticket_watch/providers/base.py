from __future__ import annotations

from datetime import date
from typing import Protocol

from ticket_watch.models import Event


class ProviderError(Exception):
    """A provider call failed (network, auth, bad response)."""


class TicketProvider(Protocol):
    name: str  # stable key stored in the db, e.g. "seatgeek"
    label: str  # display name, e.g. "SeatGeek"
    # True if lowest_price reflects the requested quantity rather than a single ticket.
    supports_quantity: bool

    def search_events(
        self, query: str, date_from: date | None = None, date_to: date | None = None, quantity: int = 1
    ) -> list[Event]: ...
