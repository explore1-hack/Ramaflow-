import asyncio

import httpx
import pytest
from conftest import join, make_admin

from database import IS_SQLITE

# SQLite has no row locks and allows one writer at a time, so these only mean something on PostgreSQL
# (run them with TEST_DATABASE_URL set; CI does).
needs_postgres = pytest.mark.skipif(IS_SQLITE, reason="concurrency guarantees need PostgreSQL row locks")


# ---------- auth ----------

def test_register_login_and_me(client):
    h = make_admin(client)
    assert client.get("/admin/me", headers=h).json()["username"] == "teacher1"


def test_wrong_password_rejected(client, admin):
    r = client.post("/admin/login", json={"identifier": "teacher1", "password": "nope-nope"})
    assert r.status_code == 401


def test_admin_routes_need_token(client):
    assert client.get("/admin/queues").status_code == 401


def test_short_password_rejected(client):
    r = client.post("/admin/register", json={"username": "abc", "email": "a@b.co", "password": "short"})
    assert r.status_code == 422


# ---------- queue creation / validation ----------

def test_unique_field_must_be_a_field(client, admin):
    r = client.post("/admin/queues", headers=admin, json={"name": "X", "fields": ["Name"], "unique_field": "Roll"})
    assert r.status_code == 422


def test_duplicate_field_names_rejected(client, admin):
    r = client.post("/admin/queues", headers=admin, json={"name": "X", "fields": ["Name", "name"], "unique_field": "Name"})
    assert r.status_code == 422


def test_teacher_cannot_touch_other_teachers_queue(client, queue):
    other = make_admin(client, "teacher2")
    assert client.get(f"/admin/queues/{queue['id']}", headers=other).status_code == 403
    assert client.post(f"/admin/queues/{queue['id']}/close", headers=other).status_code == 403


# ---------- joining ----------

def test_join_gives_sequential_positions(client, queue):
    a = join(client, queue["id"], roll="1").json()
    b = join(client, queue["id"], roll="2").json()
    assert (a["position"], b["position"]) == (1, 2)


def test_duplicate_roll_number_blocked_case_insensitive(client, queue):
    assert join(client, queue["id"], roll="21cs01").status_code == 200
    assert join(client, queue["id"], roll="21CS01").status_code == 409


def test_extra_fields_dropped_and_missing_rejected(client, queue):
    r = client.post(f"/queues/{queue['id']}/join", json={"data": {"Name": "A", "Roll No.": "9", "evil": "x"}})
    assert "evil" not in r.json()["data"]
    r = client.post(f"/queues/{queue['id']}/join", json={"data": {"Name": "A"}})
    assert r.status_code == 400


def test_overlong_value_rejected(client, queue):
    assert join(client, queue["id"], name="x" * 101).status_code == 400


def test_closed_queue_rejects_joins_but_status_still_works(client, admin, queue):
    entry = join(client, queue["id"]).json()
    client.post(f"/admin/queues/{queue['id']}/close", headers=admin)
    assert join(client, queue["id"], roll="2").status_code == 404
    assert client.get(f"/entries/{entry['id']}/status").status_code == 200
    client.post(f"/admin/queues/{queue['id']}/reopen", headers=admin)
    assert join(client, queue["id"], roll="2").status_code == 200


# ---------- admin actions ----------

def test_call_next_follows_fifo_and_status_updates(client, admin, queue):
    e1 = join(client, queue["id"], roll="1").json()
    e2 = join(client, queue["id"], roll="2").json()
    assert client.get(f"/entries/{e2['id']}/status").json()["people_ahead"] == 1
    called = client.post(f"/admin/queues/{queue['id']}/call-next", headers=admin).json()
    assert called["id"] == e1["id"] and called["status"] == "called"
    assert client.get(f"/entries/{e2['id']}/status").json()["people_ahead"] == 0


def test_illegal_transitions_rejected(client, admin, queue):
    e = join(client, queue["id"]).json()
    assert client.post(f"/admin/entries/{e['id']}/done", headers=admin).status_code == 400   # waiting -> done
    client.post(f"/admin/entries/{e['id']}/call", headers=admin)
    client.post(f"/admin/entries/{e['id']}/done", headers=admin)
    assert client.post(f"/admin/entries/{e['id']}/call", headers=admin).status_code == 400   # done -> called


def test_recall_goes_to_back_with_unique_position(client, admin, queue):
    e1 = join(client, queue["id"], roll="1").json()
    join(client, queue["id"], roll="2")
    client.post(f"/admin/entries/{e1['id']}/skip", headers=admin)
    recalled = client.post(f"/admin/entries/{e1['id']}/recall", headers=admin).json()
    new = join(client, queue["id"], roll="3").json()
    assert recalled["position"] == 3 and new["position"] == 4          # the old count()+1 bug gave both 3


def test_recall_blocked_if_same_student_rejoined(client, admin, queue):
    e1 = join(client, queue["id"], roll="1").json()
    client.post(f"/admin/entries/{e1['id']}/skip", headers=admin)
    assert join(client, queue["id"], roll="1").status_code == 200       # allowed: old entry is finished
    assert client.post(f"/admin/entries/{e1['id']}/recall", headers=admin).status_code == 409


def test_finished_student_can_rejoin(client, admin, queue):
    e = join(client, queue["id"]).json()
    client.post(f"/admin/entries/{e['id']}/call", headers=admin)
    client.post(f"/admin/entries/{e['id']}/done", headers=admin)
    assert join(client, queue["id"]).status_code == 200


# ---------- the interview-story test ----------

@needs_postgres
def test_100_parallel_joins_get_unique_consecutive_positions(client, queue):
    """100 students join at the same instant: positions must be exactly 1..100, no duplicates."""
    from main import app

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
            return await asyncio.gather(*[
                c.post(f"/queues/{queue['id']}/join", json={"data": {"Name": f"S{i}", "Roll No.": f"R{i}"}})
                for i in range(100)
            ])

    responses = asyncio.run(run())
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses if r.status_code != 200][:3]
    assert sorted(r.json()["position"] for r in responses) == list(range(1, 101))


@needs_postgres
def test_parallel_duplicate_joins_only_one_wins(client, queue):
    """20 simultaneous joins with the SAME roll number: exactly one succeeds."""
    from main import app

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
            return await asyncio.gather(*[
                c.post(f"/queues/{queue['id']}/join", json={"data": {"Name": "Same", "Roll No.": "DUP"}})
                for _ in range(20)
            ])

    codes = [r.status_code for r in asyncio.run(run())]
    assert codes.count(200) == 1 and codes.count(409) == 19, codes
