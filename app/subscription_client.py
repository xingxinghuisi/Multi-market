"""Workers submit events to the API; the API owns recipients and notification history."""
import os
import requests

API_BASE_URL = os.getenv("MARKET_RADAR_API_URL", "http://127.0.0.1:8000").rstrip("/")


def headers():
    return {"X-Radar-Worker-Token": os.getenv("RADAR_WORKER_TOKEN", "")}


def load_subscriptions(alert_type):
    response = requests.get(f"{API_BASE_URL}/api/internal/subscriptions",
                            params={"alert_type": alert_type}, headers=headers(), timeout=15)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        raise ValueError("Expected subscription list")
    return rows


def submit_event(subscription_id, event_key, title, message, **fields):
    response = requests.post(f"{API_BASE_URL}/api/internal/subscriptions/{subscription_id}/events",
        json={"event_key": event_key, "title": title, "message": message, **fields},
        headers=headers(), timeout=20)
    response.raise_for_status()
    return response.json()
