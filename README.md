# Ticket Watch

Watches ticket prices for the games you pick and pushes a phone notification (via [ntfy](https://ntfy.sh)) when the lowest price drops to or below your target. It works across marketplaces through one provider interface.

| Marketplace | Status |
|---|---|
| SeatGeek | Working. Free `client_id` from https://seatgeek.com/account/develop |
| StubHub | Adapter built against the [Catalog API](https://developer.stubhub.com/api-reference/catalog) and tested with fixtures. Credentials aren't self-serve, so request access through developer.stubhub.com. It turns on automatically once `STUBHUB_CLIENT_ID`/`SECRET` are set. Try `STUBHUB_SANDBOX=true` first. |
| Vivid Seats | Stub only. There's no public API. |

## Setup

```sh
cd ~/ticket-watch
cp .env.example .env        # fill in SEATGEEK_CLIENT_ID and NTFY_TOPIC
uv sync
uv run uvicorn ticket_watch.app:app --port 8765
```

Open http://127.0.0.1:8765, then:
1. Install the ntfy app on your phone and subscribe to your `NTFY_TOPIC`. Click **Send test notification** to check it arrives.
2. **Search** for a team, then create a watch for the whole date range or **Watch** a single game.

### Run at login (launchd)

```sh
mkdir -p logs
cp launchd/com.leo.ticketwatch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.leo.ticketwatch.plist
# stop: launchctl unload ~/Library/LaunchAgents/com.leo.ticketwatch.plist
```

Polling pauses while the Mac sleeps. The scheduler runs again on wake.

## How alerts work

- A **watch** is a set of criteria: team/performer, date range, target price, quantity, home-games-only, venue. One watch matches many games on every enabled marketplace.
- You get one alert per game per marketplace when the price first reaches your target. You get another only if it falls a further 5% or $5, whichever comes first. If the price goes back above target, the alert re-arms.
- Alerts list other marketplaces' prices for the same game when known.
- **Quantity:** neither API returns a price for N seats together, so prices are per ticket and alerts say so.
- **Home games:** SeatGeek uses each team's home venue. StubHub falls back to title conventions ("A at B" means B is home, "A vs B" means A is home). If it can't tell, the game is excluded.
- If a marketplace fails 3 checks in a row, you get a single "looks down" notification.

## Adding a marketplace

Create `ticket_watch/providers/<name>.py` with a class that has `name`, `label`, `supports_quantity`, and `search_events(query, date_from, date_to, quantity) -> list[Event]`. Raise `ProviderError` on failure. Then add it to `providers/registry.py`.

## Tests

```sh
uv run pytest
```
