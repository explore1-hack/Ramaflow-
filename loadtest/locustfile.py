"""Load test: students join a queue, then poll their status every ~5 s.

Setup: create a queue in the dashboard (fields: Name, Roll No.; unique field: Roll No.),
note its id, then:
    pip install locust
    QUEUE_ID=1 locust -f loadtest/locustfile.py --host http://localhost:8000
Open http://localhost:8089, try 200 users, spawn rate 20.
Record p95 latency and failure % from the Locust report for your README/resume.
"""
import itertools
import os
import random

from locust import HttpUser, between, task

QUEUE_ID = os.getenv("QUEUE_ID", "1")
_counter = itertools.count(1)


class Student(HttpUser):
    wait_time = between(4, 6)   # same rhythm as the browser's 5-second polling

    def on_start(self):
        n = f"{random.randint(0, 10**9)}-{next(_counter)}"
        r = self.client.post(f"/queues/{QUEUE_ID}/join",
                             json={"data": {"Name": f"Student {n}", "Roll No.": n}})
        self.entry_id = r.json().get("id") if r.status_code == 200 else None

    @task
    def poll_status(self):
        if self.entry_id:
            self.client.get(f"/entries/{self.entry_id}/status", name="/entries/[id]/status")
