from __future__ import annotations

import httpx


class NtfyNotifier:
    """Push via https://ntfy.sh. Subscribe to the same topic in the ntfy phone app.

    Anyone who knows the topic name can read it, so use a long random one.
    """

    def __init__(self, topic: str, server: str = "https://ntfy.sh", http: httpx.Client | None = None):
        self._topic = topic
        self._server = server.rstrip("/")
        self._http = http or httpx.Client(timeout=10)

    def send(self, title: str, message: str, url: str | None = None, priority: int = 3) -> None:
        # JSON publishing (vs. header-based) so titles can carry non-ASCII like "·" and emoji.
        body = {"topic": self._topic, "title": title, "message": message, "priority": priority, "tags": ["ticket"]}
        if url:
            body["click"] = url
        self._http.post(self._server, json=body).raise_for_status()
