"""Deterministic lead qualification (BANT-style) so the score is explainable and auditable.

The LLM only *extracts* facts from the conversation; the score is computed here in code.
"""

SERVICE_CITIES = {"bengaluru", "bangalore", "chennai", "hyderabad", "pune", "mumbai"}
SENTIMENT_VALUE = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


def score_lead(lead: dict) -> tuple[int, list[str]]:
    """Return (score 0-100, reasons)."""
    score, reasons = 0, []

    bill = lead.get("monthly_bill_inr") or 0          # Need / Budget
    if bill >= 2000:
        score += 25; reasons.append(f"Bill Rs {bill}/month is a strong fit (+25)")
    elif bill >= 1000:
        score += 12; reasons.append(f"Bill Rs {bill}/month is a moderate fit (+12)")

    if lead.get("is_owner") == 1:                     # Authority
        score += 25; reasons.append("Owns the property (+25)")
    elif lead.get("is_owner") == 0:
        reasons.append("Tenant, needs owner approval (+0)")

    timeline = (lead.get("timeline") or "").lower()   # Timeline
    if timeline in ("immediate", "1-3 months"):
        score += 25; reasons.append(f"Timeline {timeline} (+25)")
    elif timeline == "3-6 months":
        score += 15; reasons.append("Timeline 3-6 months (+15)")
    elif timeline:
        score += 5; reasons.append(f"Timeline {timeline} (+5)")

    ptype = (lead.get("property_type") or "").lower()  # Fit
    if ptype in ("house", "commercial"):
        score += 15; reasons.append(f"{ptype.title()} roof is installable (+15)")
    elif ptype == "apartment":
        score += 7; reasons.append("Apartment, needs society approval (+7)")

    city = (lead.get("city") or "").lower()
    if city in SERVICE_CITIES:
        score += 5; reasons.append(f"{city.title()} is in the service area (+5)")
    elif city:
        reasons.append(f"{city.title()} is outside the service area (+0)")
    if lead.get("name"):
        score += 5; reasons.append("Identified by name (+5)")
    return min(score, 100), reasons


def status_for(lead: dict, score: int) -> str:
    if lead.get("status") in ("booked", "not_interested"):
        return lead["status"]
    return "hot" if score >= 70 else "warm" if score >= 40 else "cold"
