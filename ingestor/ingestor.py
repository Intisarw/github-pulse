import csv
import os
from pathlib import Path

import requests


def get_github_events(owner: str, repo: str, token: str = None):
    url = f"https://api.github.com/repos/{owner}/{repo}/events"

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error {response.status_code}: {response.text}")
        return None


def save_events_as_csv(events, filename="github_events.csv"):
    fieldnames = ["id", "type", "actor", "repo", "created_at", "public"]

    output_path = Path(filename)

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for event in events:
            writer.writerow({
                "id": event.get("id", ""),
                "type": event.get("type", ""),
                "actor": event.get("actor", {}).get("login", ""),
                "repo": event.get("repo", {}).get("name", ""),
                "created_at": event.get("created_at", ""),
                "public": event.get("public", "")
            })

    print(f"Saved {len(events)} events to: {output_path.resolve()}")


if __name__ == "__main__":
    REPO_OWNER = "python"
    REPO_NAME = "cpython"
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

    event_list = get_github_events(REPO_OWNER, REPO_NAME, GITHUB_TOKEN)

    if event_list is not None:
        save_events_as_csv(event_list)
    else:
        print("No events found.")