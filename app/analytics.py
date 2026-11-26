"""Business insights computed from the CRM tables (feeds the dashboard)."""
import json
from collections import Counter

from . import db


def insights() -> dict:
    leads = db.rows("SELECT * FROM leads ORDER BY updated_at DESC")
    calls = db.rows("SELECT c.*, l.name, l.phone FROM calls c JOIN leads l ON l.id=c.lead_id ORDER BY c.id DESC")
    appts = db.rows("SELECT a.*, l.name, l.phone FROM appointments a JOIN leads l ON l.id=a.lead_id "
                    "ORDER BY a.starts_at")
    done = [c for c in calls if c["status"] == "completed"]
    summaries = [json.loads(c["summary_json"]) for c in done if c["summary_json"]]
    for c in calls:
        c["summary"] = json.loads(c.pop("summary_json")) if c.get("summary_json") else None

    contacted = {c["lead_id"] for c in calls}
    booked_leads = {a["lead_id"] for a in appts}
    objections = Counter(o.lower() for s in summaries for o in s.get("objections", []))
    sentiments = [c["sentiment_score"] for c in done if c["sentiment_score"] is not None]

    return {
        "kpis": {
            "total_leads": len(leads),
            "calls_completed": len(done),
            "appointments": len(appts),
            "conversion_rate_pct": round(100 * len(booked_leads) / len(contacted), 1) if contacted else 0,
            "avg_lead_score": round(sum(l["score"] for l in leads) / len(leads), 1) if leads else 0,
            "avg_sentiment": round(sum(sentiments) / len(sentiments), 2) if sentiments else 0,
            "avg_turns_per_call": round(sum(s.get("turns", 0) for s in summaries) / len(summaries), 1) if summaries else 0,
        },
        "funnel": Counter(l["status"] for l in leads),
        "outcomes": Counter(c["outcome"] for c in done),
        "top_objections": objections.most_common(5),
        "languages": Counter(c["language"] for c in calls),
        "leads": leads,
        "calls": calls[:50],
        "appointments": appts,
        "crm_events": db.rows("SELECT id, lead_id, event, delivered, created_at FROM crm_events ORDER BY id DESC LIMIT 20"),
    }
