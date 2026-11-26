"""SQLite persistence = the built-in CRM (leads, calls, messages, appointments, slots).

In production this maps 1:1 to PostgreSQL tables (see docs/ARCHITECTURE.md).
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE NOT NULL,
    name TEXT, email TEXT, city TEXT,
    property_type TEXT,            -- house / apartment / commercial
    is_owner INTEGER,              -- 1 / 0 / NULL (authority)
    monthly_bill_inr INTEGER,      -- budget proxy
    timeline TEXT,                 -- immediate / 1-3 months / 3-6 months / later
    score INTEGER DEFAULT 0,       -- 0-100 qualification score
    status TEXT DEFAULT 'new',     -- new / cold / warm / hot / booked / not_interested
    language TEXT DEFAULT 'en-IN',
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER REFERENCES leads(id),
    language TEXT,
    started_at TEXT, ended_at TEXT,
    status TEXT DEFAULT 'active',  -- active / completed
    sentiment_score REAL,          -- -1..1 average across caller turns
    outcome TEXT,                  -- booked / follow_up / not_interested / no_decision
    summary_json TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id INTEGER REFERENCES calls(id),
    role TEXT,                     -- user / assistant
    content TEXT,
    sentiment TEXT, intent TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    starts_at TEXT UNIQUE,
    is_booked INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER REFERENCES leads(id),
    call_id INTEGER REFERENCES calls(id),
    slot_id INTEGER REFERENCES slots(id),
    starts_at TEXT,
    kind TEXT DEFAULT 'Free site survey',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS crm_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER REFERENCES leads(id),
    event TEXT,                    -- lead_qualified / appointment_booked / call_summarised
    payload TEXT,
    delivered INTEGER DEFAULT 0,   -- 1 once the external CRM webhook accepted it
    created_at TEXT
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conn():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
    ensure_slots()


def ensure_slots(days: int = 7):
    """Keep the next `days` working days stocked with survey slots (10:00, 12:00, 15:00, 17:00)."""
    with conn() as c:
        day = datetime.now().replace(minute=0, second=0, microsecond=0)
        added = 0
        while added < days:
            day += timedelta(days=1)
            if day.weekday() == 6:  # no Sunday visits
                continue
            for hour in (10, 12, 15, 17):
                c.execute("INSERT OR IGNORE INTO slots(starts_at) VALUES (?)",
                          (day.replace(hour=hour).isoformat(timespec="minutes"),))
            added += 1


def rows(sql, params=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def row(sql, params=()):
    r = rows(sql, params)
    return r[0] if r else None


def execute(sql, params=()) -> int:
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


# ---------- calendar ----------
def free_slots(limit: int = 6) -> list[dict]:
    out = rows("SELECT id, starts_at FROM slots WHERE is_booked=0 AND starts_at > ? ORDER BY starts_at LIMIT ?",
               (now(), limit))
    for s in out:
        s["label"] = datetime.fromisoformat(s["starts_at"]).strftime("%a %d %b, %I:%M %p")
    return out


def book_slot(slot_id: int, lead_id: int, call_id: int) -> dict | None:
    """Atomically claim a slot (no double booking) and create the appointment."""
    with conn() as c:
        claimed = c.execute("UPDATE slots SET is_booked=1 WHERE id=? AND is_booked=0", (slot_id,)).rowcount
        if not claimed:
            return None
        starts_at = c.execute("SELECT starts_at FROM slots WHERE id=?", (slot_id,)).fetchone()[0]
        c.execute("INSERT INTO appointments(lead_id, call_id, slot_id, starts_at, created_at) VALUES (?,?,?,?,?)",
                  (lead_id, call_id, slot_id, starts_at, now()))
    return {"slot_id": slot_id, "starts_at": starts_at,
            "label": datetime.fromisoformat(starts_at).strftime("%a %d %b, %I:%M %p")}


# ---------- leads ----------
LEAD_FIELDS = {"name", "email", "city", "property_type", "is_owner", "monthly_bill_inr", "timeline",
               "score", "status", "language"}


def get_or_create_lead(phone: str, language: str) -> dict:
    lead = row("SELECT * FROM leads WHERE phone=?", (phone,))
    if lead:
        return lead
    execute("INSERT INTO leads(phone, language, created_at, updated_at) VALUES (?,?,?,?)",
            (phone, language, now(), now()))
    return row("SELECT * FROM leads WHERE phone=?", (phone,))


def update_lead(lead_id: int, fields: dict) -> dict:
    fields = {k: v for k, v in fields.items() if k in LEAD_FIELDS and v is not None}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        execute(f"UPDATE leads SET {sets}, updated_at=? WHERE id=?", (*fields.values(), now(), lead_id))
    return row("SELECT * FROM leads WHERE id=?", (lead_id,))


# ---------- calls / messages ----------
def create_call(lead_id: int, language: str) -> int:
    return execute("INSERT INTO calls(lead_id, language, started_at) VALUES (?,?,?)", (lead_id, language, now()))


def add_message(call_id: int, role: str, content: str, sentiment=None, intent=None):
    execute("INSERT INTO messages(call_id, role, content, sentiment, intent, created_at) VALUES (?,?,?,?,?,?)",
            (call_id, role, content, sentiment, intent, now()))


def get_messages(call_id: int) -> list[dict]:
    return rows("SELECT * FROM messages WHERE call_id=? ORDER BY id", (call_id,))


def past_call_summaries(lead_id: int, exclude_call: int, limit: int = 3) -> list[dict]:
    out = rows("SELECT id, started_at, summary_json FROM calls WHERE lead_id=? AND id!=? AND summary_json IS NOT NULL "
               "ORDER BY id DESC LIMIT ?", (lead_id, exclude_call, limit))
    for r in out:
        r["summary"] = json.loads(r.pop("summary_json"))
    return out
