"""CRM integration.

The local SQLite CRM is the system of record for the prototype. Every important event
(lead qualified, appointment booked, call summarised) is also pushed to CRM_WEBHOOK_URL when set,
which plugs into HubSpot / Zoho / Salesforce via their webhook-triggered workflows or Zapier / n8n.
Events are logged in `crm_events` so delivery is visible and retryable.
"""
import json
import logging
import threading
import urllib.request

from . import config, db

log = logging.getLogger("crm")


def push_event(lead_id: int, event: str, payload: dict):
    lead = db.row("SELECT * FROM leads WHERE id=?", (lead_id,))
    body = {"event": event, "lead": lead, "data": payload, "source": "ai-sales-voice-agent"}
    event_id = db.execute("INSERT INTO crm_events(lead_id, event, payload, delivered, created_at) VALUES (?,?,?,?,?)",
                          (lead_id, event, json.dumps(body, default=str), 0, db.now()))
    if config.CRM_WEBHOOK_URL:
        threading.Thread(target=_deliver, args=(event_id, body), daemon=True).start()


def _deliver(event_id: int, body: dict):
    try:
        req = urllib.request.Request(config.CRM_WEBHOOK_URL, data=json.dumps(body, default=str).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10):  # raises on 4xx/5xx
            pass
        db.execute("UPDATE crm_events SET delivered=1 WHERE id=?", (event_id,))
    except Exception as e:  # a real deployment retries from a queue
        log.warning("CRM webhook delivery failed for event %s: %s", event_id, e)
