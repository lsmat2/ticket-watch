from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx

from ticket_watch.models import Event
from ticket_watch.providers.base import ProviderError, describe_http_error

BASE_URL = "https://api.seatgeek.com/2"


class SeatGeekProvider:
    """SeatGeek Platform API. Free client_id from https://seatgeek.com/account/develop."""

    name = "seatgeek"
    label = "SeatGeek"
    # The public events endpoint only reports per-ticket stats.
    supports_quantity = False

    def __init__(self, client_id: str, client_secret: str | None = None, http: httpx.Client | None = None):
        # Basic Auth keeps credentials out of URLs (and so out of logs and error messages).
        self._auth = (client_id, client_secret or "")
        self._http = http or httpx.Client(timeout=15)

    def search_events(
        self, query: str, date_from: date | None = None, date_to: date | None = None, quantity: int = 1
    ) -> list[Event]:
        params: dict[str, str | int] = {"q": query, "per_page": 100, "sort": "datetime_local.asc"}
        if date_from:
            params["datetime_local.gte"] = date_from.isoformat()
        if date_to:
            # lte on a bare date means midnight; include the whole last day.
            params["datetime_local.lt"] = (date_to + timedelta(days=1)).isoformat()
        try:
            resp = self._http.get(f"{BASE_URL}/events", params=params, auth=self._auth)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"SeatGeek search failed: {describe_http_error(exc)}") from exc
        return [self._parse(e) for e in payload.get("events", [])]

    def _parse(self, e: dict) -> Event:
        venue = e.get("venue") or {}
        performers = e.get("performers") or []
        stats = e.get("stats") or {}
        return Event(
            provider=self.name,
            provider_event_id=str(e["id"]),
            title=e.get("title") or e.get("short_title") or "",
            # datetime_local has no offset; it's the venue's local wall-clock time.
            starts_at=datetime.fromisoformat(e["datetime_local"]),
            venue_id=str(venue["id"]) if venue.get("id") is not None else None,
            venue_name=venue.get("name") or "",
            city=venue.get("city") or "",
            url=e.get("url") or "",
            lowest_price=stats.get("lowest_price"),
            performers=tuple(p.get("name", "") for p in performers),
            home_venues=tuple(
                (p.get("name", ""), str(p["home_venue_id"])) for p in performers if p.get("home_venue_id")
            ),
        )
