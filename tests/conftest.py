import os
import sys
import tempfile
from pathlib import Path

# These must be set BEFORE the app is imported.
os.environ["APP_ENV"] = "development"
os.environ["RATE_LIMIT_ENABLED"] = "0"
os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL") or f"sqlite:///{tempfile.mkdtemp()}/test.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from database import Base, engine
from main import app


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def make_admin(client, name="teacher1"):
    client.post("/admin/register", json={"username": name, "email": f"{name}@school.edu", "password": "password123"})
    token = client.post("/admin/login", json={"identifier": name, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(client):
    return make_admin(client)


@pytest.fixture
def queue(client, admin):
    r = client.post("/admin/queues", headers=admin, json={
        "name": "Doubts", "fields": ["Name", "Roll No."], "unique_field": "Roll No.", "wait_time_estimate": 5})
    assert r.status_code == 200, r.text
    return r.json()


def join(client, queue_id, name="Asha", roll="21CS01"):
    return client.post(f"/queues/{queue_id}/join", json={"data": {"Name": name, "Roll No.": roll}})
