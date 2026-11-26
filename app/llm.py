"""LLM access through any OpenAI-compatible API, returning strict JSON.

If no LLM_API_KEY is configured (or the provider errors), a small rule-based fallback answers in
the same JSON shape. It keeps demos and tests working offline; it is English-only and much less
capable than a real model, and the UI shows which brain is active.
"""
import json
import logging
import re

from . import config

log = logging.getLogger("llm")


def _parse_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)  # tolerate ```json fences or chatter around the object
        if m:
            return json.loads(m.group(0))
        raise


class LLM:
    def __init__(self):
        self.client = None
        if config.LLM_API_KEY:
            from openai import OpenAI
            self.client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL, timeout=20)

    @property
    def mode(self) -> str:
        return f"llm:{config.LLM_MODEL}" if self.client else "fallback:rule-based"

    def complete_json(self, messages: list[dict], task: str, ctx: dict) -> dict:
        """task is 'turn' or 'summary'. ctx carries structured data used only by the fallback."""
        if self.client:
            try:
                return self._call(messages)
            except Exception as e:
                log.error("LLM call failed, using fallback: %s", e)
        return fallback_turn(ctx) if task == "turn" else fallback_summary(ctx)

    def translate(self, text: str, language: str) -> str:
        if not self.client:
            return text
        try:
            out = self._call([{"role": "system", "content": f'Translate to natural spoken {language}. '
                               'Return JSON {"text": "..."}'}, {"role": "user", "content": text}])
            return out.get("text") or text
        except Exception as e:
            log.error("translate failed: %s", e)
            return text

    def _call(self, messages):
        """Try the richest request first; some providers/models reject response_format, temperature or
        max_tokens (e.g. reasoning models), so retry with fewer parameters instead of failing the call."""
        base = dict(model=config.LLM_MODEL, messages=messages)
        attempts = [dict(response_format={"type": "json_object"}, temperature=0.3, max_tokens=1500),
                     dict(response_format={"type": "json_object"}), {}]
        last_err = None
        for extra in attempts:
            try:
                resp = self.client.chat.completions.create(**base, **extra)
                return _parse_json(resp.choices[0].message.content)
            except Exception as e:
                last_err = e
                if getattr(e, "status_code", 400) != 400:  # auth / rate limit / network: don't retry here
                    raise
        raise last_err

llm = LLM()

# ----------------------------------------------------------------------------------------------
# Rule-based fallback (offline mode)
# ----------------------------------------------------------------------------------------------
POS = {"great", "good", "yes", "interested", "sure", "nice", "perfect", "awesome", "love", "okay", "ok", "thanks",
       "helpful", "sounds"}
NEG = {"expensive", "costly", "no", "not", "busy", "annoying", "bad", "waste", "stop", "don't", "dont", "never",
       "worried", "problem", "angry"}
CITIES = ["bengaluru", "bangalore", "chennai", "hyderabad", "pune", "mumbai", "delhi", "kolkata", "jaipur"]
QUESTION_HINTS = ("price", "cost", "subsidy", "emi", "loan", "warranty", "maintenance", "monsoon", "rain", "cloud",
                  "roof", "install", "how long", "saving", "payback", "?", "what", "how", "commercial", "survey")
ASK_ORDER = [
    ("name", "May I know your name?"),
    ("city", "Which city is the property in?"),
    ("property_type", "Is it an independent house, an apartment or a commercial property?"),
    ("is_owner", "Do you own the property?"),
    ("monthly_bill_inr", "Roughly how much is your monthly electricity bill?"),
    ("timeline", "When are you hoping to get solar installed?"),
]


def _sentiment(text: str) -> str:
    words = set(re.findall(r"[a-z']+", text.lower()))
    p, n = len(words & POS), len(words & NEG)
    return "positive" if p > n else "negative" if n > p else "neutral"


def _extract(text: str) -> dict:
    t, out = text.lower(), {}
    if m := re.search(r"(?:my name is|this is|i am|i'm)\s+([a-z]+)", t):
        if m.group(1) not in {"interested", "calling", "looking", "not", "a", "the", "from", "in", "busy", "fine"}:
            out["name"] = m.group(1).title()
    if m := re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        out["email"] = m.group(0)
    for c in CITIES:
        if c in t:
            out["city"] = "Bengaluru" if c == "bangalore" else c.title()
    if re.search(r"apartment|flat", t):
        out["property_type"] = "apartment"
    elif re.search(r"shop|office|factory|commercial", t):
        out["property_type"] = "commercial"
    elif re.search(r"house|villa|bungalow|independent", t):
        out["property_type"] = "house"
    if re.search(r"\b(rent|renting|tenant)\b", t):
        out["is_owner"] = 0
    elif re.search(r"\b(own|owner|my own|our own|yes i do)\b", t):
        out["is_owner"] = 1
    if m := re.search(r"(?:rs\.?|₹|inr)?\s*(\d{1,2},?\d{3}|\d{3,5})\s*(?:rupees|rs|inr)?", t):
        val = int(m.group(1).replace(",", ""))
        if 300 <= val <= 200000 and ("bill" in t or "rupees" in t or "rs" in t or "₹" in t or "around" in t or "about" in t):
            out["monthly_bill_inr"] = val
    if re.search(r"immediate|asap|right away|this month|urgent", t):
        out["timeline"] = "immediate"
    elif re.search(r"next month|couple of months|1-3|two months|few months|soon", t):
        out["timeline"] = "1-3 months"
    elif re.search(r"six months|6 months|3-6", t):
        out["timeline"] = "3-6 months"
    elif re.search(r"next year|later|not sure when", t):
        out["timeline"] = "later"
    return out


def fallback_turn(ctx: dict) -> dict:
    text, lead, slots = ctx["user_text"], dict(ctx["lead"]), ctx["slots"]
    t = text.lower()
    updates = _extract(text)
    lead.update(updates)
    sentiment = _sentiment(text)
    action = {"type": "none"}

    if re.search(r"not interested|don't call|dont call|stop calling|remove my number", t):
        return {"reply": "No problem at all, I won't take more of your time. Have a great day!",
                "lead_updates": updates, "sentiment": "negative", "intent": "not_interested",
                "action": {"type": "end_call"}}
    if re.search(r"\b(bye|goodbye|that's all|thats all)\b", t):
        return {"reply": "Thank you for your time. Have a sunny day!", "lead_updates": updates,
                "sentiment": sentiment, "intent": "other", "action": {"type": "end_call"}}

    # Booking: the caller picks one of the slots we offered ("first one", "option 2", "the 10 am one")
    if ctx.get("slots_offered") and slots:
        pick = None
        if m := re.search(r"\b(first|1|one|second|2|two|third|3|three)\b", t):
            pick = {"first": 0, "1": 0, "one": 0, "second": 1, "2": 1, "two": 1, "third": 2, "3": 2, "three": 2}[m.group(1)]
        for i, s in enumerate(slots[:3]):
            if s["label"].lower().split(",")[-1].strip() in t:
                pick = i
        if pick is not None and pick < len(slots):
            s = slots[pick]
            return {"reply": f"Done! Your free site survey is booked for {s['label']}. Our engineer will call before arriving.",
                    "lead_updates": updates, "sentiment": "positive", "intent": "ready_to_book",
                    "action": {"type": "book_appointment", "slot_id": s["id"]}}

    parts = []
    if any(h in t for h in QUESTION_HINTS) and ctx["knowledge"]:
        body = re.sub(r"^#.*\n", "", ctx["knowledge"][0]["text"]).strip().replace("\n- ", " ")
        parts.append(" ".join(re.split(r"(?<=[.!?])\s+", body)[:2]))
    elif updates:
        parts.append("Thanks" + (f", {lead['name']}" if lead.get("name") else "") + ".")

    wants_booking = re.search(r"book|schedule|visit|survey|appointment|come and check", t)
    missing = [q for f, q in ASK_ORDER if lead.get(f) in (None, "")]
    if wants_booking or (not missing and slots):
        options = "; ".join(f"option {i + 1}, {s['label']}" for i, s in enumerate(slots[:3]))
        parts.append(f"I can book a free site survey. Available: {options}. Which works for you?")
        intent = "ready_to_book"
    elif missing:
        parts.append(missing[0])
        intent = "inquiry"
    else:
        parts.append("Would you like to book a free site survey?")
        intent = "inquiry"
    return {"reply": " ".join(parts), "lead_updates": updates, "sentiment": sentiment, "intent": intent,
            "action": action}


def fallback_summary(ctx: dict) -> dict:
    lead, msgs = ctx["lead"], ctx["messages"]
    user_text = " ".join(m["content"].lower() for m in msgs if m["role"] == "user")
    objections = [o for o, k in [("price", "expensive"), ("price", "costly"), ("monsoon/cloudy days", "monsoon"),
                                 ("renting", "rent"), ("needs family discussion", "family")] if k in user_text]
    known = ", ".join(f"{k.replace('_', ' ')}: {lead[k]}" for k in
                      ("name", "city", "property_type", "monthly_bill_inr", "timeline") if lead.get(k))
    return {"summary": f"Caller discussed rooftop solar. Known details: {known or 'none captured'}.",
            "key_points": [m["content"] for m in msgs if m["role"] == "user"][:3],
            "objections": sorted(set(objections)),
            "next_steps": "Engineer to conduct the booked site survey." if ctx.get("booked")
            else "Follow up with a call or WhatsApp brochure in 2-3 days."}
