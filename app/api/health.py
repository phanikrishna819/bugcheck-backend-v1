from fastapi import APIRouter

from app.agent.llm import router as model_router

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "llm": model_router.describe()}
