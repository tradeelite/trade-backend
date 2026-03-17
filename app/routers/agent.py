"""TEARIA — conversational AI using Gemini Flash with per-session history."""

from collections import defaultdict

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.db.schemas import AgentQueryRequest, AgentQueryResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])

# In-memory conversation history keyed by session_id
# Each entry: {"role": "user"|"model", "text": str}
_sessions: dict[str, list[dict]] = defaultdict(list)
_SESSION_MAX_MESSAGES = 40  # keep last 40 messages (~20 turns)

_SYSTEM_PROMPT = """You are TEARIA, the AI Research & Insights Assistant for TradeElite — a personal trading intelligence platform.

Your role is to help traders and investors with:
- Stock analysis: fundamentals, valuation, technical signals, price action
- News and sentiment interpretation for specific stocks
- Portfolio and options strategy questions
- Explaining financial metrics, indicators, and trading concepts in plain English
- Macro market conditions and sector trends

Guidelines:
- Respond conversationally and clearly — no raw JSON, no code blocks unless explicitly asked
- Be concise and actionable — traders value clarity over verbose explanations
- When the user mentions a specific stock or ticker, focus your response on that context
- If given context about which page/tab the user is viewing (e.g. Fundamental AI, Technical Analysis), tailor your answer to what they're likely looking at
- Always note that your analysis is informational only, not financial advice
- If you don't have real-time data, say so clearly and work from general knowledge
"""


@router.post("/query", response_model=AgentQueryResponse)
async def query_agent(body: AgentQueryRequest) -> AgentQueryResponse:
    try:
        import vertexai
        from vertexai.generative_models import Content, GenerativeModel, Part

        vertexai.init(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )

        model = GenerativeModel(
            "gemini-2.0-flash-001",
            system_instruction=_SYSTEM_PROMPT,
        )

        # Retrieve and trim session history
        history = _sessions[body.session_id]
        if len(history) > _SESSION_MAX_MESSAGES:
            history = history[-_SESSION_MAX_MESSAGES:]
            _sessions[body.session_id] = history

        # Build Gemini Content history (all messages except the current one)
        gemini_history = [
            Content(role=msg["role"], parts=[Part.from_text(msg["text"])])
            for msg in history
        ]

        # Send message with full history
        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(body.message)
        response_text = response.text or ""

        # Persist this turn to session
        history.append({"role": "user", "text": body.message})
        history.append({"role": "model", "text": response_text})

        return AgentQueryResponse(response=response_text, session_id=body.session_id)

    except Exception as e:
        raise HTTPException(500, f"TEARIA query failed: {e}")
