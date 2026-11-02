import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def db(tmp_path):
    """A fresh database with the sample data loaded, for every test."""
    from app.db import database
    from app.db.seed import load_sample
    os.environ["RELIEFGRID_DB"] = str(tmp_path / "test.db")
    database.close_conn()
    load_sample()
    yield database.get_conn()
    database.close_conn()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def make_request(rid, item="Water", quantity=10, urgency="moderate", shelter="S1", priority=2,
                 created="2026-10-31T10:00:00", allocated=0, lat=25.2, lon=55.3):
    """A request dict in the shape the engine expects."""
    return {"id": rid, "shelter_id": shelter, "item": item, "quantity": quantity, "allocated": allocated,
            "urgency": urgency, "created_at": created, "shelter_priority": priority, "lat": lat, "lon": lon}
