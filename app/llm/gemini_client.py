"""
Wraps google-genai (the current Gen AI SDK — the older `google-generativeai`
package is deprecated). One client, reused across the run.

Free-tier RPM is small and model-dependent (Google's own rate-limits page:
https://ai.google.dev/gemini-api/docs/rate-limits — check it for your
model/date rather than trusting a number baked into this file). We enforce
our own ceiling client-side via GEMINI_MAX_REQUESTS_PER_MINUTE so a big
upload degrades to "slower" instead of "a wall of 429s".
"""
import json
import re
import time
from collections import deque
from typing import Optional

from google import genai
from google.genai import types

from app.config import settings


class RateLimiter:
    def __init__(self, max_per_minute: int):
        self.max_per_minute = max(1, max_per_minute)
        self.timestamps: deque[float] = deque()

    def wait_for_slot(self):
        now = time.monotonic()
        while self.timestamps and now - self.timestamps[0] > 60:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.max_per_minute:
            sleep_for = 60 - (now - self.timestamps[0]) + 0.1
            if sleep_for > 0:
                time.sleep(sleep_for)
        self.timestamps.append(time.monotonic())


class GeminiClient:
    def __init__(self):
        self.enabled = bool(settings.gemini_api_key)
        self._client = genai.Client(api_key=settings.gemini_api_key) if self.enabled else None
        self._limiter = RateLimiter(settings.gemini_max_requests_per_minute)

    def generate_json(self, system_prompt: str, user_prompt: str, max_retries: int = 4) -> Optional[list | dict]:
        """Call Gemini asking for a strict JSON response and parse it.
        Returns None if the client isn't configured, or if every retry
        failed (a run should degrade to static-only findings, not crash)."""
        if not self.enabled:
            return None

        last_error = None
        for attempt in range(max_retries):
            self._limiter.wait_for_slot()
            try:
                response = self._client.models.generate_content(
                    model=settings.gemini_model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                text = response.text or ""
                return _parse_json_loose(text)
            except Exception as exc:  # noqa: BLE001 — SDK error types vary by transport
                last_error = exc
                is_rate_limit = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
                backoff = (2 ** attempt) if is_rate_limit else 1
                time.sleep(backoff)
        # All retries exhausted — caller treats this file as static-only.
        print(f"[gemini_client] giving up after {max_retries} attempts: {last_error}")
        return None


def _parse_json_loose(text: str):
    text = text.strip()
    # Strip ``` json fences if the model added them despite JSON mode
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


gemini_client = GeminiClient()
