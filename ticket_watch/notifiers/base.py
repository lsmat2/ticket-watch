from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    def send(self, title: str, message: str, url: str | None = None, priority: int = 3) -> None:
        """priority follows ntfy's 1 (min) .. 5 (urgent) scale."""
        ...
