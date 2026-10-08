from __future__ import annotations

from enum import Enum

# A repeat alert for the same event needs the price to fall by at least this much
# (whichever threshold is reached first) below the last alerted price.
MIN_FURTHER_DROP_PCT = 0.05
MIN_FURTHER_DROP_ABS = 5.0


class Decision(Enum):
    NOTIFY = "notify"  # send an alert and record it
    SKIP = "skip"  # do nothing
    REARM = "rearm"  # price went back above target: forget the last alert


def decide(price: float | None, target: float, last_alert_price: float | None) -> Decision:
    if price is None:
        return Decision.SKIP
    if price > target:
        return Decision.REARM if last_alert_price is not None else Decision.SKIP
    if last_alert_price is None:
        return Decision.NOTIFY
    threshold = min(MIN_FURTHER_DROP_ABS, last_alert_price * MIN_FURTHER_DROP_PCT)
    # Round to cents so 54.00 -> 51.30 (exactly 5%) isn't lost to float error.
    if round(last_alert_price - price, 2) >= round(threshold, 2):
        return Decision.NOTIFY
    return Decision.SKIP
