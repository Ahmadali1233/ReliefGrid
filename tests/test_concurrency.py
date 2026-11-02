"""Screens refresh while changes are saved: reads must never see a change half-done, and nothing may freeze."""
import threading


def test_reads_and_writes_at_the_same_time(client):
    bad = []

    def reader():
        for _ in range(15):
            for path in ("/api/summary", "/api/network", "/api/events?limit=300", "/api/inventory", "/api/dispatch"):
                r = client.get(path)
                if r.status_code != 200:
                    bad.append((path, r.status_code, r.text[:80]))

    def writer():
        for i in range(12):
            r = client.post("/api/requests", json={"shelter_id": "SH-07", "item": "Water", "quantity": 5 + i, "urgency": "high"})
            if r.status_code != 201:
                bad.append(("add", r.status_code, r.text[:80]))
            client.post("/api/undo")

    threads = [threading.Thread(target=reader) for _ in range(4)] + [threading.Thread(target=writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "something froze"
    assert not bad, bad[:3]
    c = client.get("/api/integrity").json()
    assert c["passed"] == c["total"]
