from dataclasses import replace
from datetime import datetime

from ticket_watch.db import Database
from ticket_watch.models import Event, Watch
from ticket_watch.poller import FAILURES_BEFORE_DOWN_ALERT, run_cycle
from ticket_watch.providers.base import ProviderError


def make_event(provider="seatgeek", price=50.0, event_id="e1", title="Boston Celtics at New York Knicks"):
    return Event(
        provider=provider,
        provider_event_id=event_id,
        title=title,
        starts_at=datetime(2099, 11, 14, 19, 30),
        venue_id="1",
        venue_name="Madison Square Garden",
        city="New York",
        url=f"https://{provider}.example/{event_id}",
        lowest_price=price,
    )


class FakeProvider:
    supports_quantity = False

    def __init__(self, name, events=(), fail=False):
        self.name = name
        self.label = name.title()
        self.events = list(events)
        self.fail = fail
        self.calls = 0

    def search_events(self, query, date_from=None, date_to=None, quantity=1):
        self.calls += 1
        if self.fail:
            raise ProviderError("boom")
        return self.events


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, message, url=None, priority=3):
        self.sent.append({"title": title, "message": message, "url": url, "priority": priority})


def setup(target=60.0, **kw):
    db = Database(":memory:")
    db.add_watch(Watch(id=None, query="Knicks", target_price=target, **kw))
    return db, FakeNotifier()


def test_alerts_once_then_suppresses_repeat():
    db, n = setup()
    sg = FakeProvider("seatgeek", [make_event(price=54)])
    run_cycle(db, [sg], n)
    run_cycle(db, [sg], n)
    assert len(n.sent) == 1
    assert "$54" in n.sent[0]["title"]
    assert n.sent[0]["url"] == "https://seatgeek.example/e1"


def test_further_drop_alerts_again_and_rearm_after_rise():
    db, n = setup()
    sg = FakeProvider("seatgeek", [make_event(price=54)])
    run_cycle(db, [sg], n)
    sg.events = [make_event(price=45)]
    run_cycle(db, [sg], n)
    assert len(n.sent) == 2
    sg.events = [make_event(price=80)]
    run_cycle(db, [sg], n)
    sg.events = [make_event(price=55)]
    run_cycle(db, [sg], n)
    assert len(n.sent) == 3


def test_alert_mentions_other_provider_price_for_same_game():
    db, n = setup()
    sh = FakeProvider("stubhub", [make_event("stubhub", price=70, event_id="s1", title="Knicks vs Celtics")])
    sg = FakeProvider("seatgeek", [make_event(price=54)])
    run_cycle(db, [sh, sg], n)
    [alert] = n.sent
    assert "Stubhub $70" in alert["message"]


def test_home_only_filter_skips_away_games():
    db, n = setup(home_only=True)
    away = make_event(price=10, event_id="away", title="New York Knicks at Boston Celtics")
    run_cycle(db, [FakeProvider("seatgeek", [away])], n)
    assert n.sent == []


def test_quantity_caveat_when_provider_cannot_filter():
    db, n = setup(quantity=2)
    run_cycle(db, [FakeProvider("seatgeek", [make_event(price=54)])], n)
    assert "per ticket" in n.sent[0]["message"]


def test_failing_provider_does_not_block_others_and_alerts_once_when_down():
    db, n = setup()
    bad = FakeProvider("stubhub", fail=True)
    good = FakeProvider("seatgeek", [make_event(price=54)])
    for _ in range(FAILURES_BEFORE_DOWN_ALERT + 2):
        run_cycle(db, [bad, good], n)
    titles = [a["title"] for a in n.sent]
    assert sum("$54" in t for t in titles) == 1
    assert sum("down" in t.lower() for t in titles) == 1


def test_paused_watch_is_not_polled():
    db, n = setup()
    db.set_watch_active(1, False)
    sg = FakeProvider("seatgeek", [make_event(price=10)])
    run_cycle(db, [sg], n)
    assert sg.calls == 0


def test_only_watch_ids_limits_cycle():
    db, n = setup()
    db.add_watch(Watch(id=None, query="Rangers", target_price=100))
    sg = FakeProvider("seatgeek", [make_event(price=10)])
    run_cycle(db, [sg], n, watch_ids=[2])
    assert sg.calls == 1


def test_unpriced_event_is_tracked_without_alert():
    db, n = setup()
    run_cycle(db, [FakeProvider("seatgeek", [replace(make_event(), lowest_price=None)])], n)
    assert n.sent == []
    assert len(db.tracked_events(1)) == 1


def test_provider_failure_counts_once_per_cycle_regardless_of_watch_count():
    db, n = setup()
    db.add_watch(Watch(id=None, query="Rangers", target_price=100))
    db.add_watch(Watch(id=None, query="Mets", target_price=100))
    bad = FakeProvider("stubhub", fail=True)
    run_cycle(db, [bad], n)
    assert bad.calls == 1
    assert db.provider_statuses()["stubhub"]["consecutive_failures"] == 1
    assert n.sent == []
