from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from app import db
from app.pipeline import run_pipeline
from app.uploads.handler import extract_upload, cleanup_run

app = FastAPI(
    title="Frontend Bug Check API",
    description="Uploads an Angular/React app, runs static + AI-assisted analysis, "
                "returns a bug report with suggested fixes.",
    version="0.1.0",
)

# Wide open for now since there's no UI origin yet; tighten this once the
# interactive UI has a known origin.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    db.init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    """Upload a .zip of an Angular or React app. Runs the full pipeline
    synchronously and returns the report. For large apps this can take a
    while (LLM calls are rate-limited) — once a UI exists, this should
    become a background job with a polling/streaming status endpoint
    instead of a blocking request; see README "Making this async"."""
    workspace_root, run_id = extract_upload(file)
    try:
        report, md_path, html_path = run_pipeline(workspace_root, run_id)
        db.save_run(report, str(md_path), str(html_path))
        return report
    finally:
        cleanup_run(run_id)


@app.get("/api/runs")
def get_runs(limit: int = 50):
    return db.list_runs(limit)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    return run


@app.get("/api/runs/{run_id}/report.md")
def get_run_markdown(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    return FileResponse(run["md_path"], media_type="text/markdown")


@app.get("/api/runs/{run_id}/report.html", response_class=HTMLResponse)
def get_run_html(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    return FileResponse(run["html_path"], media_type="text/html")
