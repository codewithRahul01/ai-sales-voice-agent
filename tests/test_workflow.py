"""End-to-end tests. Run: pytest -q  (works offline: uses the rule-based fallback brain)."""
import json
import os
import tempfile
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["LLM_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.llm import llm  # noqa: E402
from app.main import app  # noqa: E402
from app.qualification import score_lead  # noqa: E402
from app.rag import kb  # noqa: E402

client = TestClient(app)


def talk(call_id, text):
    r = client.post(f"/api/calls/{call_id}/turn", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_sales_workflow_books_and_summarises():
    start = client.post("/api/calls", json={"phone": "9000000001", "language": "en-IN"}).json()
    cid = start["call_id"]
    assert "SunVolt" in start["greeting"]

    talk(cid, "Yes, my name is Ravi")
    talk(cid, "I live in Bengaluru in an independent house")
    r = talk(cid, "Yes I own it. What about the subsidy?")
    assert "Government subsidy" in r["retrieved"]               # RAG hit
    assert "78,000" in r["reply"]                                # grounded answer
    talk(cid, "My bill is around 4,000 rupees")
    r = talk(cid, "Isn't it expensive though?")
    assert r["sentiment"] == "negative"                          # sentiment analysis
    r = talk(cid, "We want it next month")
    assert r["score"] == 100 and r["lead"]["status"] == "hot"    # qualification
    r = talk(cid, "Book the first one")
    assert r["booking"] and r["lead"]["status"] == "booked"      # appointment booking

    summary = client.post(f"/api/calls/{cid}/end").json()
    assert summary["outcome"] == "booked" and "price" in summary["objections"]

    dash = client.get("/api/dashboard").json()                   # CRM + insights
    assert dash["kpis"]["appointments"] >= 1
    events = {e["event"] for e in dash["crm_events"]}
    assert {"lead_qualified", "appointment_booked", "call_summarised"} <= events


def test_returning_caller_memory_and_language():
    start = client.post("/api/calls", json={"phone": "9000000001", "language": "hi-IN"}).json()
    assert start["returning_caller"] and "Ravi" in start["greeting"] and "नमस्ते" in start["greeting"]


def test_not_interested_ends_call():
    cid = client.post("/api/calls", json={"phone": "9000000002", "language": "en-IN"}).json()["call_id"]
    r = talk(cid, "I'm not interested, please don't call again")
    assert r["ended"] and r["lead"]["status"] == "not_interested"
    assert client.post(f"/api/calls/{cid}/turn", json={"text": "hello"}).status_code == 404


def test_no_double_booking():
    slot = db.free_slots(1)[0]
    lead = db.get_or_create_lead("9000000003", "en-IN")
    cid = db.create_call(lead["id"], "en-IN")
    assert db.book_slot(slot["id"], lead["id"], cid)
    assert db.book_slot(slot["id"], lead["id"], cid) is None


def test_rag_ranks_relevant_section():
    assert kb.search("is EMI or a loan available")[0].title == "EMI and financing"
    assert kb.search("what happens in monsoon cloudy days")[0].title.startswith("Objection: what about monsoon")


def test_score_is_deterministic():
    s, reasons = score_lead({"monthly_bill_inr": 5000, "is_owner": 1, "timeline": "immediate",
                             "property_type": "house", "city": "Pune", "name": "A"})
    assert s == 100 and len(reasons) == 6
    assert score_lead({"is_owner": 0, "monthly_bill_inr": 800})[0] == 0


def test_llm_json_path_and_output_validation(monkeypatch):
    """Simulate a real provider: malformed/unsafe fields must be rejected, unoffered slots refused."""
    payload = {"reply": "Great, let me book that.", "sentiment": "positive", "intent": "ready_to_book",
               "lead_updates": {"name": "Meera", "monthly_bill_inr": "3,200", "is_owner": "maybe",
                                "property_type": "castle", "timeline": "1-3 months"},
               "action": {"type": "book_appointment", "slot_id": 999999}}
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="```json\n" + json.dumps(payload) + "\n```"))]))))
    monkeypatch.setattr(llm, "client", fake)
    cid = client.post("/api/calls", json={"phone": "9000000004", "language": "en-IN"}).json()["call_id"]
    r = talk(cid, "Book me in")
    assert r["lead"]["name"] == "Meera" and r["lead"]["monthly_bill_inr"] == 3200
    assert r["lead"]["is_owner"] is None and r["lead"]["property_type"] is None   # invalid values dropped
    assert r["booking"] is None and "no longer available" in r["reply"]          # hallucinated slot refused


@pytest.mark.parametrize("bad", [{"text": ""}, {"text": "x" * 1001}])
def test_input_validation(bad):
    cid = client.post("/api/calls", json={"phone": "9000000005"}).json()["call_id"]
    assert client.post(f"/api/calls/{cid}/turn", json=bad).status_code == 422
