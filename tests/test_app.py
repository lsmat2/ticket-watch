import os

os.environ["DB_PATH"] = ":memory:"
for key in ("SEATGEEK_CLIENT_ID", "STUBHUB_CLIENT_ID", "STUBHUB_CLIENT_SECRET", "NTFY_TOPIC"):
    os.environ[key] = ""

from fastapi.testclient import TestClient  # noqa: E402

from ticket_watch import app as app_module  # noqa: E402

# no `with`: skips lifespan, so no scheduler thread. Origin mimics the browser on this app's own pages.
client = TestClient(app_module.app, headers={"Origin": "http://testserver"})


def test_pages_render_and_watch_lifecycle():
    assert client.get("/").status_code == 200
    assert client.get("/search", params={"q": "Knicks"}).status_code == 200

    resp = client.post(
        "/watches",
        data={"query": "Knicks", "target_price": "60", "date_from": "2026-11-01", "home_only": "true"},
    )
    assert resp.status_code == 200  # followed the 303 back to /
    [w] = app_module.db.list_watches()
    assert (w.query, w.target_price, w.home_only, w.date_to) == ("Knicks", 60, True, None)
    assert "Knicks" in resp.text

    client.post(f"/watches/{w.id}/toggle")
    assert app_module.db.get_watch(w.id).active is False
    client.post(f"/watches/{w.id}/delete")
    assert app_module.db.list_watches() == []


def test_test_notification_without_topic_logs():
    resp = client.post("/test-notification")
    assert "NTFY_TOPIC not set" in resp.text


def test_cross_origin_posts_are_blocked():
    before = len(app_module.db.list_watches())
    evil = TestClient(app_module.app, headers={"Origin": "https://evil.example"})
    assert evil.post("/watches", data={"query": "x", "target_price": "1"}).status_code == 403
    assert TestClient(app_module.app).post("/check").status_code == 403  # no Origin/Referer at all
    assert len(app_module.db.list_watches()) == before
    referer_only = TestClient(app_module.app, headers={"Referer": "http://testserver/search?q=x"})
    assert referer_only.post("/check", follow_redirects=False).status_code == 303
