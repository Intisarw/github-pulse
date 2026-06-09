"""Central config. Read from env so secrets never live in code."""
import os

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # raises your rate limit 60 -> 5000/hr
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pulse:pulse@localhost:5432/pulse")
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "1.0"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))
ROLLUP_INTERVAL_SECONDS = float(os.getenv("ROLLUP_INTERVAL_SECONDS", "15"))
ROLLUP_WINDOW_MINUTES = int(os.getenv("ROLLUP_WINDOW_MINUTES", "5"))
