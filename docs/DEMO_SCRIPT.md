# Demo script (about 7 minutes)

**Before the demo:** set a real LLM key in `.env` and check that the header pill shows `llm:<model>` and not `fallback`. Use Chrome, allow the microphone, and open `/dashboard` in a second tab. Start from a fresh database: `rm data/crm.db`.

## 1. Business problem (1 min)
Leads go cold, telecaller capacity is limited, and qualification is inconsistent. Show the requirement table in `docs/ARCHITECTURE.md`.

## 2. End-to-end workflow, live voice (3 min)
Phone `9876543210`, language **English**, then **Start call**. Speak:

1. "Yes, it's a good time. My name is Ravi." *(the lead card fills in)*
2. "I have an independent house in Bengaluru, and I own it."
3. "What subsidy can I get?" *(the RAG pill shows "Government subsidy" and the answer cites ₹78,000)*
4. "My bill is around four thousand rupees a month. Isn't solar expensive though?" *(objection handled from knowledge; sentiment turns red)*
5. "Okay, we'd like to do it in the next month or two." *(score reaches 100, status hot, the agent offers slots)*
6. "Book the Thursday 10 AM slot." *(Booked card appears)*
7. Click **End call** → the AI summary appears. Switch to the dashboard: lead, appointment, CRM events, summary and KPIs.

## 3. Memory and multilingual (1 min)
Start a new call with the **same phone number**, language **Hindi**. The agent greets Ravi by name in Hindi and knows about the booked survey. Ask in Hindi: "मेरा सर्वे कब है?" ("When is my survey?")

## 4. Architecture, scale, security, cost (2 min)
Walk through `architecture_prototype.png`, then `architecture_production.png`, the 1 lakh users table, and the cost per minute table.

## Live-coding exercises to be ready for
| Request | Where to change |
|---|---|
| Add a qualification field (e.g. roof size) | `db.py` schema + `LEAD_FIELDS`, `agent.TURN_SCHEMA`, `agent.clean_updates`, `qualification.score_lead`, `static/app.js` `FIELDS` |
| Change scoring weights or thresholds | `qualification.py` |
| Add knowledge | Drop a `.md` file with `# Section` headings into `knowledge/` and restart |
| Add a language | `agent.LANGUAGES` (+ optional greeting in `GREETINGS`) |
| Hand off to a human on negative sentiment | In `handle_turn`, count `negative` turns → set action / push a `handoff_requested` CRM event |
| Swap the LLM provider | `.env`: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` |
| Change booking hours | `db.ensure_slots` |
| Debug a turn | `GET /api/calls/{id}` shows the transcript with per-turn sentiment and intent; the server log shows LLM errors |
