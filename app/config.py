"""Central configuration, read from environment variables (.env supported)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Any OpenAI-compatible provider works: OpenAI, Groq, Google Gemini, Together, local Ollama.
#   Groq:   LLM_BASE_URL=https://api.groq.com/openai/v1             LLM_MODEL=openai/gpt-oss-120b
#   Gemini: LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/  LLM_MODEL=gemini-3.6-flash
#   OpenAI: LLM_BASE_URL=(leave empty)                              LLM_MODEL=gpt-4o-mini
#   Ollama: LLM_BASE_URL=http://localhost:11434/v1  LLM_API_KEY=ollama  LLM_MODEL=llama3.1
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or None
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "crm.db"))
KNOWLEDGE_DIR = BASE_DIR / "knowledge"

# Optional: push qualified leads / bookings to an external CRM (HubSpot workflow, Zapier, n8n, Make...)
CRM_WEBHOOK_URL = os.getenv("CRM_WEBHOOK_URL", "")

COMPANY_NAME = os.getenv("COMPANY_NAME", "SunVolt Solar")
AGENT_NAME = os.getenv("AGENT_NAME", "Asha")
MAX_HISTORY_TURNS = 12  # short-term memory window sent to the LLM
