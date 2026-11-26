"""HTTP API + static UI.  Run:  uvicorn app.main:app --reload"""
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, analytics, config, db
from .llm import llm

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="AI Sales Voice Agent", version="1.0")
db.init_db()


class StartCall(BaseModel):
    phone: str = Field(min_length=6, max_length=20, description="Caller ID / lead phone number")
    language: str = "en-IN"


class Turn(BaseModel):
    text: str = Field(min_length=1, max_length=1000, description="Caller utterance from STT")


@app.get("/health")
def health():
    return {"ok": True, "brain": llm.mode, "knowledge_chunks": len(agent.kb.chunks)}


@app.post("/api/calls")
def start_call(body: StartCall):
    db.ensure_slots()
    return agent.start_call(body.phone, body.language)


@app.post("/api/calls/{call_id}/turn")
def turn(call_id: int, body: Turn):
    try:
        return agent.handle_turn(call_id, body.text.strip())
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/calls/{call_id}/end")
def end(call_id: int):
    if not db.row("SELECT id FROM calls WHERE id=?", (call_id,)):
        raise HTTPException(404, "Call not found")
    return agent.end_call(call_id)


@app.get("/api/calls/{call_id}")
def get_call(call_id: int):
    call = db.row("SELECT * FROM calls WHERE id=?", (call_id,))
    if not call:
        raise HTTPException(404, "Call not found")
    return {"call": call, "messages": db.get_messages(call_id)}


@app.get("/api/slots")
def slots():
    return db.free_slots(20)


@app.get("/api/dashboard")
def dashboard():
    return analytics.insights()


@app.get("/api/languages")
def languages():
    return agent.LANGUAGES


app.mount("/static", StaticFiles(directory=config.BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(config.BASE_DIR / "static" / "index.html")


@app.get("/dashboard")
def dashboard_page():
    return FileResponse(config.BASE_DIR / "static" / "dashboard.html")
