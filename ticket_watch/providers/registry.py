from __future__ import annotations

import os

from ticket_watch.providers.base import TicketProvider
from ticket_watch.providers.seatgeek import SeatGeekProvider
from ticket_watch.providers.stubhub import StubHubProvider


def enabled_providers() -> list[TicketProvider]:
    """Providers whose credentials are present in the environment."""
    providers: list[TicketProvider] = []
    if os.getenv("STUBHUB_CLIENT_ID") and os.getenv("STUBHUB_CLIENT_SECRET"):
        providers.append(
            StubHubProvider(
                os.environ["STUBHUB_CLIENT_ID"],
                os.environ["STUBHUB_CLIENT_SECRET"],
                sandbox=os.getenv("STUBHUB_SANDBOX", "").lower() in ("1", "true", "yes"),
            )
        )
    if os.getenv("SEATGEEK_CLIENT_ID"):
        providers.append(SeatGeekProvider(os.environ["SEATGEEK_CLIENT_ID"], os.getenv("SEATGEEK_CLIENT_SECRET")))
    # VividSeatsProvider: add here once it has a real implementation.
    return providers
