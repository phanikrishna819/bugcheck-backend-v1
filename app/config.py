"""
Central settings object. Everything here is overridable via env vars / .env
so nothing is hardcoded the way the original skill files warn against
(see detect-environment.md: "Never hardcode").
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_max_requests_per_minute: int = 8

    max_files_for_llm: int = 40

    database_path: str = "./bugcheck.db"
    upload_tmp_dir: str = "./tmp_uploads"
    reports_dir: str = "./reports"

    max_upload_mb: int = 200

    @property
    def upload_tmp_path(self) -> Path:
        p = Path(self.upload_tmp_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def reports_path(self) -> Path:
        p = Path(self.reports_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
