from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.workspace import resolver

router = APIRouter(prefix="/api", tags=["workspaces"])


class RegisterWorkspaceRequest(BaseModel):
    path: str = Field(min_length=1)


@router.post("/workspaces")
def register_workspace(request: RegisterWorkspaceRequest):
    return {"path": resolver.bind(request.path)}
