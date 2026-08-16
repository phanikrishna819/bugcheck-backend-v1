import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import UploadFile, HTTPException

from app.config import settings


def _is_within_directory(directory: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def extract_upload(upload: UploadFile) -> tuple[Path, str]:
    """Saves the uploaded zip, validates it, extracts it into a fresh
    per-run directory under UPLOAD_TMP_DIR, and returns (extracted_root,
    run_id). Guards against zip-slip (entries that escape the extraction
    dir via `../`) and oversized uploads."""
    if not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Please upload a .zip archive of the frontend app.")

    run_id = uuid.uuid4().hex[:12]
    run_dir = settings.upload_tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    zip_path = run_dir / "upload.zip"

    size = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    with open(zip_path, "wb") as f:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                shutil.rmtree(run_dir, ignore_errors=True)
                raise HTTPException(413, f"Upload exceeds {settings.max_upload_mb} MB limit.")
            f.write(chunk)

    extract_dir = run_dir / "app"
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                dest = extract_dir / member.filename
                if not _is_within_directory(extract_dir, dest):
                    raise HTTPException(400, f"Unsafe path in zip archive: {member.filename}")
            zf.extractall(extract_dir)
    except zipfile.BadZipFile:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise HTTPException(400, "That doesn't look like a valid zip file.")

    zip_path.unlink(missing_ok=True)

    # If the zip contained a single top-level folder, treat that as the
    # real app root (common when people zip a project folder directly).
    entries = [p for p in extract_dir.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0], run_id

    return extract_dir, run_id


def cleanup_run(run_id: str):
    run_dir = settings.upload_tmp_path / run_id
    shutil.rmtree(run_dir, ignore_errors=True)
