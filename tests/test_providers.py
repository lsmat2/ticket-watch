import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from ticket_watch.matching import is_home_game
from ticket_watch.providers.base import ProviderError
from ticket_watch.providers.seatgeek import SeatGeekProvider
from ticket_watch.providers.stubhub import TOKEN_URL, StubHubProvider

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


@respx.mock
def test_seatgeek_parses_events_and_sends_filters():
    route = respx.get("https://api.seatgeek.com/2/events").mock(
        return_value=httpx.Response(200, json=load("seatgeek_events.json"))
    )
    events = SeatGeekProvider("cid").search_events("Knicks", date(2026, 11, 1), date(2026, 11, 30))

    params = route.calls.last.request.url.params
    assert params["client_id"] == "cid"
    assert params["q"] == "Knicks"
    assert params["datetime_local.gte"] == "2026-11-01"
    assert params["datetime_local.lt"] == "2026-12-01"

    first, second = events
    assert first.provider_event_id == "6123456"
    assert first.lowest_price == 54
    assert first.venue_name == "Madison Square Garden"
    assert first.starts_at.hour == 19
    assert is_home_game(first, "Knicks") is True
    assert is_home_game(second, "Knicks") is False
    assert second.lowest_price is None


@respx.mock
def test_seatgeek_http_error_raises_provider_error():
    respx.get("https://api.seatgeek.com/2/events").mock(return_value=httpx.Response(403))
    with pytest.raises(ProviderError):
        SeatGeekProvider("bad").search_events("Knicks")


@respx.mock
def test_stubhub_authenticates_once_and_filters_dates_locally():
    token = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    )
    search = respx.get("https://api.stubhub.net/catalog/events/search").mock(
        return_value=httpx.Response(200, json=load("stubhub_search.json"))
    )
    sh = StubHubProvider("id", "secret")
    events = sh.search_events("Knicks", date(2026, 11, 1), date(2026, 11, 30))
    sh.search_events("Knicks")

    assert token.call_count == 1  # token cached across calls
    assert token.calls.last.request.headers["authorization"].startswith("Basic ")
    assert search.calls.last.request.headers["authorization"] == "Bearer tok"

    [e] = events  # the February game is outside the range
    assert e.lowest_price == 61.5
    assert e.url.endswith("/event/153000111/")
    assert e.venue_name == "Madison Square Garden"
    assert is_home_game(e, "Knicks") is True  # "Home vs Away" title convention


@respx.mock
def test_stubhub_sandbox_uses_sandbox_host():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "t"}))
    route = respx.get("https://sandbox.api.stubhub.net/catalog/events/search").mock(
        return_value=httpx.Response(200, json={"_embedded": {"items": []}})
    )
    assert StubHubProvider("id", "s", sandbox=True).search_events("x") == []
    assert route.called
