from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from ticket_watch.db import Database
from ticket_watch.matching import game_key
from ticket_watch.models import Event, Watch
from ticket_watch.notifiers.ntfy import NtfyNotifier
from ticket_watch.poller import run_cycle
from ticket_watch.providers.base import ProviderError
from ticket_watch.providers.registry import enabled_providers

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ticket_watch")


class LogNotifier:
    """Fallback when NTFY_TOPIC isn't set, so the app still runs."""

    def send(self, title, message, url=None, priority=3):
        log.info("NOTIFY %s | %s | %s", title, message.replace("\n", " / "), url)


db = Database(os.getenv("DB_PATH", ROOT / "ticket_watch.db"))
providers = enabled_providers()
notifier = (
    NtfyNotifier(os.environ["NTFY_TOPIC"], os.getenv("NTFY_SERVER", "https://ntfy.sh"))
    if os.getenv("NTFY_TOPIC")
    else LogNotifier()
)
# Every marketplace the app knows about, connected or not, for the header.
MARKETS = [("stubhub", "StubHub"), ("seatgeek", "SeatGeek"), ("vividseats", "Vivid Seats")]
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))

# The scheduler and "Check now" can overlap; serialize cycles so an alert is never sent twice.
_cycle_lock = threading.Lock()
last_cycle: dict[str, datetime | None] = {"at": None}


def poll(watch_ids: list[int] | None = None) -> None:
    with _cycle_lock:
        try:
            run_cycle(db, providers, notifier, watch_ids=watch_ids)
        except Exception:
            log.exception("poll cycle crashed")
        if watch_ids is None:
            last_cycle["at"] = datetime.now()


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(poll, "interval", minutes=POLL_MINUTES, next_run_time=datetime.now(), max_instances=1)
    scheduler.start()
    log.info("providers: %s; polling every %d min", [p.name for p in providers] or "NONE", POLL_MINUTES)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _ctx(request: Request, **extra):
    return {
        "request": request,
        "providers": providers,
        "labels": {p.name: p.label for p in providers},
        "markets": [
            {"label": label, "connected": any(p.name == name for p in providers)} for name, label in MARKETS
        ],
        "ntfy_on": not isinstance(notifier, LogNotifier),
        "poll_minutes": POLL_MINUTES,
        **extra,
    }


@app.get("/")
def index(request: Request, notice: str | None = None):
    watches = [(w, db.tracked_events(w.id)) for w in db.list_watches()]
    return templates.TemplateResponse(
        request,
        "watches.html",
        _ctx(
            request,
            watches=watches,
            statuses=db.provider_statuses(),
            last_cycle=last_cycle["at"],
            notice=notice,
        ),
    )


@app.get("/search")
def search(request: Request, q: str = "", date_from: str = "", date_to: str = ""):
    games: list[dict] = []
    errors: dict[str, str] = {}
    if q.strip():
        by_game: dict[tuple, dict] = {}
        for p in providers:
            try:
                events = p.search_events(q.strip(), _date(date_from), _date(date_to))
            except ProviderError as exc:
                errors[p.label] = str(exc)
                continue
            if events and all(e.lowest_price is None for e in events):
                errors[p.label] = (
                    f"found {len(events)} games but shared no prices. Your API key doesn't include price data, "
                    "so watches can't alert from this marketplace yet."
                )
            for e in events:
                key = game_key(e)
                game = by_game.setdefault(key, {"starts_at": key[0], "event": e, "offers": {}})
                game["offers"][p.label] = e
        games = [by_game[k] for k in sorted(by_game)]
    return templates.TemplateResponse(
        request,
        "search.html",
        _ctx(request, q=q, date_from=date_from, date_to=date_to, games=games, errors=errors),
    )


@app.post("/watches")
def create_watch(
    background: BackgroundTasks,
    query: str = Form(...),
    target_price: float = Form(...),
    date_from: str = Form(""),
    date_to: str = Form(""),
    quantity: int = Form(1),
    home_only: bool = Form(False),
    venue_name: str = Form(""),
):
    watch_id = db.add_watch(
        Watch(
            id=None,
            query=query.strip(),
            target_price=target_price,
            date_from=_date(date_from),
            date_to=_date(date_to),
            quantity=max(1, quantity),
            home_only=home_only,
            venue_name=venue_name.strip() or None,
        )
    )
    background.add_task(poll, [watch_id])
    return RedirectResponse("/?notice=Watch+added%3B+checking+prices+now", status_code=303)


@app.post("/watches/{watch_id}/toggle")
def toggle_watch(watch_id: int):
    if w := db.get_watch(watch_id):
        db.set_watch_active(watch_id, not w.active)
    return RedirectResponse("/", status_code=303)


@app.post("/watches/{watch_id}/delete")
def delete_watch(watch_id: int):
    db.delete_watch(watch_id)
    return RedirectResponse("/", status_code=303)


@app.post("/check")
def check_now(background: BackgroundTasks):
    background.add_task(poll)
    return RedirectResponse("/?notice=Checking+all+watches", status_code=303)


@app.post("/test-notification")
def test_notification():
    try:
        notifier.send("Ticket Watch test", "Notifications are working.", priority=3)
        notice = "Test notification sent" if not isinstance(notifier, LogNotifier) else "NTFY_TOPIC not set; logged instead"
    except Exception as exc:
        notice = f"Notification failed: {exc}"
    return RedirectResponse(f"/?notice={quote(notice)}", status_code=303)


def _price(e: Event | None) -> str:
    return f"${e.lowest_price:,.0f}" if e and e.lowest_price is not None else "—"


templates.env.filters["price"] = _price
def _dt(d: str | datetime) -> datetime:
    return datetime.fromisoformat(d) if isinstance(d, str) else d


templates.env.filters["dow"] = lambda d: _dt(d).strftime("%a")
templates.env.filters["mon"] = lambda d: _dt(d).strftime("%b")
templates.env.filters["day"] = lambda d: _dt(d).strftime("%-d")
templates.env.filters["clock"] = lambda d: _dt(d).strftime("%-I:%M %p")
templates.env.filters["shortdate"] = lambda d: (d if isinstance(d, date) else _dt(d)).strftime("%b %-d, %Y")
