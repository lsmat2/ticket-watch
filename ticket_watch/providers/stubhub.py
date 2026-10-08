from __future__ import annotations

import time
from datetime import date, datetime

import httpx

from ticket_watch.models import Event
from ticket_watch.providers.base import ProviderError, describe_http_error

TOKEN_URL = "https://account.stubhub.com/oauth2/token"
API_URL = "https://api.stubhub.net"
SANDBOX_API_URL = "https://sandbox.api.stubhub.net"


class StubHubProvider:
    """StubHub Catalog API (application-only OAuth2, scope read:events).

    Credentials aren't self-serve; request access via https://developer.stubhub.com.
    """

    name = "stubhub"
    label = "StubHub"
    # min_ticket_price is event-level, not per-quantity.
    supports_quantity = False

    def __init__(
        self, client_id: str, client_secret: str, sandbox: bool = False, http: httpx.Client | None = None
    ):
        self._creds = (client_id, client_secret)
        self._base = SANDBOX_API_URL if sandbox else API_URL
        self._http = http or httpx.Client(timeout=15)
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _access_token(self) -> str:
        # Refresh a minute early so a token never expires mid-request.
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        try:
            resp = self._http.post(
                TOKEN_URL,
                auth=self._creds,
                data={"grant_type": "client_credentials", "scope": "read:events"},
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"StubHub auth failed: {describe_http_error(exc)}") from exc
        self._token = body["access_token"]
        self._token_expires_at = time.time() + float(body.get("expires_in", 3600))
        return self._token

    def search_events(
        self, query: str, date_from: date | None = None, date_to: date | None = None, quantity: int = 1
    ) -> list[Event]:
        # Search only filters by a single dateLocal, so the range is applied after fetching.
        params = {"q": query, "page_size": 100, "exclude_parking_passes": "true"}
        try:
            resp = self._http.get(
                f"{self._base}/catalog/events/search",
                params=params,
                headers={
                    "Authorization": f"Bearer {self._access_token()}",
                    "Accept": "application/hal+json",
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"StubHub search failed: {describe_http_error(exc)}") from exc
        events = [self._parse(e) for e in (payload.get("_embedded") or {}).get("items", [])]
        return [
            ev
            for ev in events
            if (date_from is None or ev.starts_at.date() >= date_from)
            and (date_to is None or ev.starts_at.date() <= date_to)
        ]

    def _parse(self, e: dict) -> Event:
        venue = (e.get("_embedded") or {}).get("venue") or {}
        price = e.get("min_ticket_price") or {}
        links = e.get("_links") or {}
        return Event(
            provider=self.name,
            provider_event_id=str(e["id"]),
            title=e.get("name") or "",
            starts_at=datetime.fromisoformat(e["start_date"]),
            venue_id=str(venue["id"]) if venue.get("id") is not None else None,
            venue_name=venue.get("name") or "",
            city=venue.get("city") or "",
            url=(links.get("event:webpage") or {}).get("href", ""),
            lowest_price=price.get("amount"),
            currency=price.get("currency_code") or "USD",
        )
