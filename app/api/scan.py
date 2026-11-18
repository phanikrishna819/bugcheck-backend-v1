"""The original zip-upload scan pipeline, kept as an additive feature."""
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from app import db
from app.pipeline import run_pipeline
from app.uploads.handler import cleanup_run, extract_upload

router = APIRouter(prefix="/api", tags=["scan"])


@router.post("/analyze")
def analyze(file: UploadFile = File(...)):
    """Blocking by design; declared sync so Starlette runs it in the threadpool
    instead of stalling the event loop (the old `async def` + sleep-based
    rate limiter froze every other request during a scan)."""
    workspace_root, run_id = extract_upload(file)
    try:
        report, md_path, html_path = run_pipeline(workspace_root, run_id)
        db.save_run(report, str(md_path), str(html_path))
        return report
    finally:
        cleanup_run(run_id)


@router.get("/runs")
def get_runs(limit: int = 50):
    return db.list_runs(limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    return run


@router.get("/runs/{run_id}/report.md")
def get_run_markdown(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    return FileResponse(run["md_path"], media_type="text/markdown")


@router.get("/runs/{run_id}/report.html", response_class=HTMLResponse)
def get_run_html(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    return FileResponse(run["html_path"], media_type="text/html")
