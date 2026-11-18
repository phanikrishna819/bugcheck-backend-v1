"""
JSON-mode helper for the scan pipeline.

Keeps the original Gemini SDK path (it has its own RPM throttle, which matters
on the free tier) and falls back to the OpenAI-compatible router when only an
OpenAI key is configured. Callers treat `None` as "no AI pass this run".
"""
from app.agent.llm import router
from app.config import settings
from app.llm.gemini_client import gemini_client


def llm_available() -> bool:
    return settings.llm_configured()


def generate_json(system_prompt: str, user_prompt: str):
    if settings.has_gemini():
        return gemini_client.generate_json(system_prompt, user_prompt)
    if settings.has_openai():
        return router.complete_json("scan", system_prompt, user_prompt)
    return None
