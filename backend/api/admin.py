from fastapi import APIRouter, Depends

from backend.services import reporter, auth
from backend.services import media as media_service
from backend.collectors import news

router = APIRouter()


@router.get("/api/admin/agent-config")
def get_agent_config(user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Snapshot read-only da config do agente. Exige auth. Sem secrets."""
    return {
        "agent": reporter.describe_config(),
        "audio": media_service.describe_config(),
        "news": news.describe_config(),
    }
