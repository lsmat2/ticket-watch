from __future__ import annotations

from datetime import date

from ticket_watch.models import Event


class VividSeatsProvider:
    """Placeholder: Vivid Seats has no public buyer-side API.

    Implement search_events here if partner/affiliate API access becomes available,
    then enable it in registry.py.
    """

    name = "vividseats"
    label = "Vivid Seats"
    supports_quantity = False

    def search_events(
        self, query: str, date_from: date | None = None, date_to: date | None = None, quantity: int = 1
    ) -> list[Event]:
        raise NotImplementedError("Vivid Seats has no public API")
