from dataclasses import replace
from datetime import datetime

from ticket_watch.matching import is_home_game, matches
from ticket_watch.models import Event, Watch


def ev(title, venue_id="1", venue_name="Madison Square Garden", home_venues=(), when="2026-11-14T19:30:00"):
    return Event(
        provider="seatgeek",
        provider_event_id="e1",
        title=title,
        starts_at=datetime.fromisoformat(when),
        venue_id=venue_id,
        venue_name=venue_name,
        city="New York",
        url="https://example.com",
        lowest_price=50.0,
        home_venues=home_venues,
    )


def test_home_game_by_performer_home_venue():
    home = (("New York Knicks", "1"), ("Boston Celtics", "2"))
    assert is_home_game(ev("Celtics at Knicks", venue_id="1", home_venues=home), "Knicks") is True
    assert is_home_game(ev("Knicks at Celtics", venue_id="2", home_venues=home), "Knicks") is False


def test_home_game_title_heuristics_when_no_venue_data():
    assert is_home_game(ev("Boston Celtics at New York Knicks"), "knicks") is True
    assert is_home_game(ev("New York Knicks at Boston Celtics"), "knicks") is False
    assert is_home_game(ev("New York Knicks vs Boston Celtics"), "knicks") is True
    assert is_home_game(ev("Boston Celtics vs. New York Knicks"), "knicks") is False


def test_unknown_home_status_is_excluded():
    assert is_home_game(ev("Knicks Fan Fest"), "knicks") is False


def test_matches_applies_venue_and_home_filters():
    w = Watch(id=1, query="Knicks", target_price=60, home_only=True)
    assert matches(w, ev("Boston Celtics at New York Knicks"))
    assert not matches(w, ev("New York Knicks at Boston Celtics"))

    w = Watch(id=1, query="Knicks", target_price=60, venue_name="garden")
    assert matches(w, ev("Anything"))
    assert not matches(w, ev("Anything", venue_name="Barclays Center"))


def test_game_key_separates_same_time_games_in_different_cities():
    from ticket_watch.matching import game_key

    nba = ev("New York Knicks at New Orleans Pelicans", when="2026-12-16T19:00:00")
    gleague = replace(nba, title="Westchester Knicks at Long Island Nets", city="Uniondale")
    assert game_key(nba) != game_key(gleague)
    stubhub_copy = replace(nba, provider="stubhub", starts_at=datetime.fromisoformat("2026-12-16T19:00:00-06:00"))
    assert game_key(nba) == game_key(stubhub_copy)
