from __future__ import annotations

import logging
from collections.abc import Iterable

from ticket_watch.db import Database
from ticket_watch.matching import game_key, matches
from ticket_watch.models import Event, Watch
from ticket_watch.notifiers.base import Notifier
from ticket_watch.providers.base import ProviderError, TicketProvider
from ticket_watch.rules import Decision, decide

log = logging.getLogger(__name__)

FAILURES_BEFORE_DOWN_ALERT = 3


def _format_alert(watch: Watch, event: Event, label: str, others: list[str], qty_verified: bool):
    when = event.starts_at.strftime("%a %b %-d %-I:%M%p").replace(":00", "").lower().capitalize()
    lines = [f"{when} · {event.venue_name}", f"{label} ${event.lowest_price:,.0f} (target ${watch.target_price:,.0f})"]
    if watch.quantity > 1 and not qty_verified:
        lines.append(f"Lowest per ticket; availability of {watch.quantity} together not verified")
    if others:
        lines.append("Also: " + ", ".join(others))
    return f"${event.lowest_price:,.0f} · {event.title}", "\n".join(lines)


def run_cycle(
    db: Database,
    providers: list[TicketProvider],
    notifier: Notifier,
    watch_ids: Iterable[int] | None = None,
) -> None:
    watches = db.list_watches(active_only=True)
    if watch_ids is not None:
        wanted = set(watch_ids)
        watches = [w for w in watches if w.id in wanted]
    if not watches:
        return

    # A provider that errors is skipped for the rest of the cycle and counted as one failure,
    # however many watches there are.
    failed: dict[str, str] = {}
    succeeded: set[str] = set()

    for watch in watches:
        # Collect every provider's results first so alerts can quote competing prices.
        found: list[tuple[TicketProvider, Event]] = []
        for p in providers:
            if p.name in failed:
                continue
            try:
                events = p.search_events(watch.query, watch.date_from, watch.date_to, watch.quantity)
            except ProviderError as exc:
                failed[p.name] = str(exc)
                continue
            succeeded.add(p.name)
            found += [(p, e) for e in events if matches(watch, e)]

        for p, event in found:
            db.record_event(watch.id, event)
            last = db.last_alert_price(watch.id, p.name, event.provider_event_id)
            decision = decide(event.lowest_price, watch.target_price, last)
            if decision is Decision.REARM:
                db.clear_alert(watch.id, p.name, event.provider_event_id)
            elif decision is Decision.NOTIFY:
                others = [
                    f"{op.label} ${oe.lowest_price:,.0f}"
                    for op, oe in found
                    if op.name != p.name and oe.lowest_price is not None and game_key(oe) == game_key(event)
                ]
                title, message = _format_alert(watch, event, p.label, others, p.supports_quantity)
                try:
                    notifier.send(title, message, url=event.url, priority=4)
                except Exception:
                    # Don't record the alert, so it's retried next cycle.
                    log.exception("notification failed for %s", event.title)
                    continue
                db.record_alert(watch.id, p.name, event.provider_event_id, event.lowest_price)

    for p in providers:
        if p.name in failed:
            _record_failure(db, notifier, p, failed[p.name])
        elif p.name in succeeded:
            db.provider_ok(p.name)


def _record_failure(db: Database, notifier: Notifier, p: TicketProvider, error: str) -> None:
    log.warning("%s failed: %s", p.name, error)
    status = db.provider_failed(p.name, error)
    if status["consecutive_failures"] >= FAILURES_BEFORE_DOWN_ALERT and not status["down_notified"]:
        try:
            notifier.send(f"{p.label} looks down", f"{status['consecutive_failures']} failed checks in a row.\n{error}")
            db.mark_provider_down_notified(p.name)
        except Exception:
            log.exception("could not send provider-down notice")
