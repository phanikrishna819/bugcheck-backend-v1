from fastapi import APIRouter

from app.agent.prompts import assets_root, list_skill_names

router = APIRouter(prefix="/api", tags=["skills"])


@router.get("/skills")
def get_skills():
    return {"assetsRoot": str(assets_root()), "skills": list_skill_names()}
