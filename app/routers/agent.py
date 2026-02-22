"""Agent query proxy — forwards requests to Vertex AI Agent Engine."""

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.db.schemas import AgentQueryRequest, AgentQueryResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/query", response_model=AgentQueryResponse)
async def query_agent(body: AgentQueryRequest) -> AgentQueryResponse:
    if not settings.tradeview_agent_resource_id:
        raise HTTPException(503, "Agent not configured — set TRADEVIEW_AGENT_RESOURCE_ID")

    try:
        import vertexai
        from vertexai import agent_engines

        vertexai.init(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )

        remote_agent = agent_engines.get(settings.tradeview_agent_resource_id)
        session = remote_agent.create_session(user_id=body.session_id)

        response_text = ""
        for event in remote_agent.stream_query(
            user_id=body.session_id,
            session_id=session["id"],
            message=body.message,
        ):
            if hasattr(event, "text") and event.text:
                response_text += event.text

        remote_agent.delete_session(user_id=body.session_id, session_id=session["id"])
        return AgentQueryResponse(response=response_text, session_id=body.session_id)

    except Exception as e:
        raise HTTPException(500, f"Agent query failed: {e}")
