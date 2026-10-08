from __future__ import annotations

from datetime import date
from typing import Protocol

import httpx

from ticket_watch.models import Event


class ProviderError(Exception):
    """A provider call failed (network, auth, bad response)."""


def describe_http_error(exc: Exception) -> str:
    """Short, URL-free description of a failed request.

    httpx's own messages include the full request URL. That can carry credentials, and these
    messages end up in logs, the db, the UI and push notifications.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "request timed out"
    if isinstance(exc, httpx.HTTPError):
        return f"network error ({type(exc).__name__})"
    return "invalid response"


class TicketProvider(Protocol):
    name: str  # stable key stored in the db, e.g. "seatgeek"
    label: str  # display name, e.g. "SeatGeek"
    # True if lowest_price reflects the requested quantity rather than a single ticket.
    supports_quantity: bool

    def search_events(
        self, query: str, date_from: date | None = None, date_to: date | None = None, quantity: int = 1
    ) -> list[Event]: ...
