"""
Load test the READ path. Run the API (make api), then `make loadtest`.

The number you want for your README/DESIGN.md:
  "Sustained X req/s at p95 < Y ms; degraded at Z; root cause was ___."
Get it from the Locust UI, then chase the bottleneck.
"""
from locust import HttpUser, between, task


class DashboardUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def trending(self):
        self.client.get("/trending/repos?minutes=60&limit=20")

    @task(1)
    def event_types(self):
        self.client.get("/stats/event-types?minutes=60")
