# Project Report: Autonomous AI Sales Voice Agent

**Candidate:** Rahul Jangra · **Demo business:** SunVolt Solar (fictional rooftop-solar installer, India)

## 1. Business problem
Sales teams lose leads because callbacks take hours, telecallers work office hours in one or two languages, and qualification is inconsistent. This prototype is an AI voice agent that calls or answers every lead instantly, 24x7, in the lead's language. It answers questions from approved company knowledge, qualifies the lead, handles objections, books a site survey, updates the CRM and summarises each call for managers.

## 2. What was built (working prototype)
| Feature | Implementation |
|---|---|
| Real-time voice | Browser streaming STT (Web Speech API) + TTS (speechSynthesis), auto-listen, barge-in |
| Memory + multilingual | Last 12 turns + CRM profile + past call summaries and appointments (keyed by phone); 8 languages |
| Qualification + sentiment | LLM extracts facts as JSON → **deterministic BANT score (0–100) in code**; per-turn sentiment and intent |
| RAG | BM25 retrieval over the markdown knowledge base; top-3 sections go into the prompt; sources shown live |
| Booking + CRM | Slot calendar with atomic booking (no double booking); SQLite CRM + webhook events to HubSpot/Zoho/Zapier |
| Summary + insights | Post-call LLM summary (objections, next steps, outcome); dashboard with conversion, funnel, objections |

**Stack:** Python, FastAPI, SQLite, vanilla JS. LLM is any OpenAI-compatible provider (Groq `openai/gpt-oss-120b` in the demo), with a rule-based offline fallback. 9 automated end-to-end tests.

**End-to-end workflow:** greeting → questions answered from RAG → qualification → objection handled → survey booked → AI summary → CRM events → dashboard. When the same number calls back, the agent greets the caller by name in Hindi and knows about the booking.

## 3. Key design decisions
- **The LLM handles language; code applies business rules.** The model returns JSON. Code validates every field, computes the score and books only a slot that was actually offered, so outputs are auditable and hallucinated bookings are impossible.
- **One structured LLM call per turn** keeps latency low and the design provider-agnostic.
- **Swap points for production:** BM25 → hybrid vector search (pgvector); browser STT/TTS → Deepgram streaming; SQLite → PostgreSQL + Redis.

## 4. Scalability (1,00,000 users)
1 lakh leads/month × 1.5 calls × 4 min = 6 lakh min/month, which is about 40 concurrent calls on average and about 200 at peak; the design targets 1,000. Plan:
- stateless, autoscaled Kubernetes pods (ap-south-1), with call state in Redis;
- PostgreSQL with read replicas;
- a queue for summaries and CRM sync;
- a multi-provider router for LLM/STT/TTS with fallbacks.

Latency target is under 1.2 s from the caller's voice to the agent's reply.

## 5. Security and compliance
- **India regulation:** DPDP Act 2023 (consent, erasure); TRAI DND scrubbing and calling-hour windows.
- **Disclosure:** the agent announces that it is an AI and that the call is recorded.
- **Data protection:** TLS + AES-256 encryption, RBAC, audit logs, zero-retention LLM contracts.
- **Already in the prototype:** input validation, LLM output validation, prompt-injection guard, XSS escaping, parameterised SQL.

## 6. Cost and commercial feasibility
About **₹4.25 per call minute**, or about ₹17 per 4-minute call:
- telephony ₹0.40
- STT ₹0.81
- TTS ₹1.06
- LLM ₹1.58
- other ₹0.40

At 1 lakh leads/month that is about **₹25.5 lakh**, against about ₹56 lakh for the 160 telecallers needed for the same volume. Pricing ₹8–10 per minute gives about 47% gross margin.

*Full details: `docs/ARCHITECTURE.md` · Diagrams: `docs/*.png` · Demo: `docs/DEMO_SCRIPT.md`*