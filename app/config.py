"""
Central settings object. Everything here is overridable via env vars / .env
so nothing is hardcoded (see detect-environment.md: "Never hardcode").
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
BUNDLED_ASSETS_DIR = BASE_DIR / "assets"

DEFAULT_ALLOWED_COMMANDS = (
    "git,ls,dir,cat,type,find,grep,rg,head,tail,wc,"
    "python,python3,pip,node,npm,npx,pnpm,yarn,"
    "mvn,gradle,pytest,jest,vitest,tsc,eslint,ng,"
    "dotnet,go,cargo,rustc,javac,java"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- agent prompt assets ---
    # Blank means "use the bundled app/assets" (bugcheck.agent.md + skills/).
    agent_assets_dir: str = ""

    # --- LLM routing ---
    # llm_provider: auto | openai | gemini. "auto" picks per purpose based on
    # which keys exist: chat prefers OpenAI-compatible tool calling, the static
    # scan pass prefers Gemini's free tier (matching the original pipeline).
    llm_provider: str = "auto"
    llm_chat_provider: str = ""
    llm_scan_provider: str = ""
    llm_chat_model: str = ""
    llm_scan_model: str = ""
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 3

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    # Gemini exposes an OpenAI-compatible surface, so chat tool calls use one
    # client implementation for every provider. The scan pass keeps using the
    # google-genai SDK (app.llm.gemini_client) for JSON-mode + RPM throttling.
    gemini_openai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_max_requests_per_minute: int = 8

    # --- agent limits ---
    agent_max_tool_rounds: int = 8
    agent_temperature: float = 0.1
    agent_max_output_chars: int = 24_000
    agent_max_history_messages: int = 40
    agent_max_file_bytes: int = 256_000
    agent_max_walk_depth: int = 8
    agent_command_timeout_seconds: int = 60
    agent_allow_shell: bool = True
    agent_allowed_commands: str = DEFAULT_ALLOWED_COMMANDS

    # --- workspace binding ---
    # both | local | clone
    workspace_mode: str = "both"
    workspace_dir: str = "./tmp_workspaces"
    clone_timeout_seconds: int = 180
    clone_max_repo_mb: int = 500

    # --- sessions ---
    session_ttl_minutes: int = 720
    # The on-demand PDF report is a synchronous request; keep the LLM pass
    # small enough to finish inside the proxy timeout on the free tier.
    pdf_max_files_for_llm: int = 12

    # --- existing scan pipeline ---
    max_files_for_llm: int = 40
    database_path: str = "./bugcheck.db"
    upload_tmp_dir: str = "./tmp_uploads"
    reports_dir: str = "./reports"
    max_upload_mb: int = 200
    max_extracted_mb: int = 500
    max_extracted_files: int = 20_000

    # --- HTTP ---
    cors_allow_origins: str = "*"

    # --- derived paths -----------------------------------------------------

    @property
    def assets_path(self) -> Path:
        if self.agent_assets_dir.strip():
            return Path(self.agent_assets_dir).expanduser().resolve()
        return BUNDLED_ASSETS_DIR

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

    @property
    def workspace_path(self) -> Path:
        p = Path(self.workspace_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def allowed_commands(self) -> set[str]:
        return {c.strip().lower() for c in self.agent_allowed_commands.split(",") if c.strip()}

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()] or ["*"]

    # --- LLM availability --------------------------------------------------

    def has_openai(self) -> bool:
        return bool(self.openai_api_key.strip())

    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key.strip())

    def llm_configured(self) -> bool:
        return self.has_openai() or self.has_gemini()


settings = Settings()
