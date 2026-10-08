from ticket_watch.rules import Decision, decide


def test_first_time_at_or_below_target_notifies():
    assert decide(price=60.0, target=60.0, last_alert_price=None) is Decision.NOTIFY
    assert decide(price=45.0, target=60.0, last_alert_price=None) is Decision.NOTIFY


def test_above_target_never_alerted_skips():
    assert decide(price=61.0, target=60.0, last_alert_price=None) is Decision.SKIP


def test_unknown_price_skips_and_keeps_state():
    assert decide(price=None, target=60.0, last_alert_price=50.0) is Decision.SKIP


def test_same_or_slightly_lower_price_is_suppressed():
    assert decide(price=54.0, target=60.0, last_alert_price=54.0) is Decision.SKIP
    # $1 drop on $54 is under both 5% ($2.70) and $5
    assert decide(price=53.0, target=60.0, last_alert_price=54.0) is Decision.SKIP


def test_price_ticking_up_but_still_under_target_is_suppressed():
    assert decide(price=57.0, target=60.0, last_alert_price=54.0) is Decision.SKIP


def test_further_drop_of_five_percent_notifies():
    # 5% of 54 = 2.70
    assert decide(price=51.30, target=60.0, last_alert_price=54.0) is Decision.NOTIFY


def test_further_drop_of_five_dollars_notifies_on_expensive_tickets():
    # 5% of 400 = 20, but a $5 drop is enough
    assert decide(price=395.0, target=450.0, last_alert_price=400.0) is Decision.NOTIFY
    assert decide(price=396.0, target=450.0, last_alert_price=400.0) is Decision.SKIP


def test_rising_back_above_target_rearms():
    assert decide(price=70.0, target=60.0, last_alert_price=54.0) is Decision.REARM
