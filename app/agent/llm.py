"""
One OpenAI-compatible client, a provider router, and a JSON helper.

Gemini exposes an OpenAI-compatible endpoint, so the agent tool loop has a
single transport for both providers (see `gemini_openai_base_url`). The
router decides *which* provider/model to use per purpose ("chat" for the
tool loop, "scan" for the per-file JSON pass) based on the configured keys:

  * explicit    - LLM_PROVIDER / LLM_CHAT_PROVIDER / LLM_SCAN_PROVIDER
  * auto        - chat prefers OpenAI tool-calling, scan prefers Gemini's
                  free tier, each with the other provider as a fallback.

A provider that fails (bad key, 404 model, 429 after retries) falls through
to the next candidate, so having both keys set is genuinely redundant.
"""
import json
import re
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings


class LLMError(Exception):
    """Raised when no configured provider could complete the request."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class AssistantTurn:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    message: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    api_key: str
    base_url: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model}


def _usage_note(body: str, limit: int = 300) -> str:
    text = (body or "").strip().replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


class ChatModel:
    """Thin synchronous OpenAI-compatible chat-completions client."""

    def __init__(self, config: ModelConfig, timeout: float, max_retries: int):
        self.config = config
        self.max_retries = max(1, max_retries)
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            timeout=httpx.Timeout(timeout, connect=15.0, write=30.0, pool=10.0),
        )

    def complete(self, messages: list[dict], tools: list[dict] | None = None,
                 temperature: float = 0.1, response_format: dict | None = None) -> AssistantTurn:
        payload: dict = {"model": self.config.model, "messages": messages, "temperature": temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if response_format:
            payload["response_format"] = response_format

        last_error = "no attempt made"
        for attempt in range(self.max_retries):
            try:
                response = self._client.post("/chat/completions", json=payload)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(min(2 ** attempt, 8))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}: {_usage_note(response.text)}"
                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if (retry_after or "").isdigit() else min(2 ** attempt, 8)
                time.sleep(delay)
                continue

            if response.status_code >= 400:
                raise LLMError(
                    f"{self.config.label} rejected the request "
                    f"(HTTP {response.status_code}): {_usage_note(response.text)}"
                )

            try:
                data = response.json()
                message = data["choices"][0]["message"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise LLMError(f"{self.config.label} returned an unexpected response shape.")

            content = message.get("content") or ""
            tool_calls = [
                ToolCall(
                    id=call.get("id") or f"call_{index}",
                    name=(call.get("function") or {}).get("name", ""),
                    arguments=(call.get("function") or {}).get("arguments") or "{}",
                )
                for index, call in enumerate(message.get("tool_calls") or [])
            ]
            replay = {"role": "assistant", "content": content}
            if message.get("tool_calls"):
                replay["tool_calls"] = message["tool_calls"]
            return AssistantTurn(content=content, tool_calls=tool_calls, message=replay)

        raise LLMError(f"{self.config.label} unavailable after {self.max_retries} attempts: {last_error}")

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | list | None:
        turn = self.complete(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return parse_json_loose(turn.content)


def parse_json_loose(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class ModelRouter:
    """Chooses a provider/model per purpose and falls through on failure."""

    def __init__(self, config=settings):
        self.settings = config
        self._models: dict[str, ChatModel] = {}

    # -- provider selection --------------------------------------------------

    def _override(self, purpose: str) -> str:
        value = (
            self.settings.llm_chat_provider if purpose == "chat" else self.settings.llm_scan_provider
        ).strip().lower()
        if value in ("openai", "gemini"):
            return value
        global_value = self.settings.llm_provider.strip().lower()
        return global_value if global_value in ("openai", "gemini") else ""

    def _candidate_providers(self, purpose: str) -> list[str]:
        override = self._override(purpose)
        if override:
            order = [override, "gemini" if override == "openai" else "openai"]
        elif purpose == "chat":
            order = ["openai", "gemini"]
        else:
            order = ["gemini", "openai"]
        return order

    def candidates(self, purpose: str) -> list[ModelConfig]:
        result = []
        for provider in self._candidate_providers(purpose):
            if provider == "openai" and self.settings.has_openai():
                model = (
                    self.settings.llm_chat_model if purpose == "chat" else self.settings.llm_scan_model
                ) or self.settings.openai_model
                result.append(ModelConfig(
                    "openai", model, self.settings.openai_api_key, self.settings.openai_base_url,
                ))
            elif provider == "gemini" and self.settings.has_gemini():
                model = (
                    self.settings.llm_chat_model if purpose == "chat" else self.settings.llm_scan_model
                ) or self.settings.gemini_model
                result.append(ModelConfig(
                    "gemini", model, self.settings.gemini_api_key,
                    self.settings.gemini_openai_base_url,
                ))
        return result

    def _model(self, config: ModelConfig) -> ChatModel:
        key = f"{config.label}|{config.base_url}"
        if key not in self._models:
            self._models[key] = ChatModel(
                config, self.settings.llm_timeout_seconds, self.settings.llm_max_retries,
            )
        return self._models[key]

    # -- public API ----------------------------------------------------------

    def complete(self, purpose: str, messages: list[dict], tools: list[dict] | None = None,
                 temperature: float = 0.1) -> AssistantTurn:
        candidates = self.candidates(purpose)
        if not candidates:
            raise LLMError(
                "No LLM provider is configured. Set OPENAI_API_KEY and/or GEMINI_API_KEY."
            )
        errors = []
        for config in candidates:
            try:
                return self._model(config).complete(messages, tools=tools, temperature=temperature)
            except LLMError as exc:
                errors.append(str(exc))
        joined = " | ".join(errors)
        raise LLMError(f"All configured LLM providers failed: {joined}")

    def complete_json(self, purpose: str, system_prompt: str, user_prompt: str):
        candidates = self.candidates(purpose)
        errors = []
        for config in candidates:
            try:
                return self._model(config).complete_json(system_prompt, user_prompt)
            except LLMError as exc:
                errors.append(str(exc))
        if errors:
            print(f"[model_router] json pass unavailable: {' | '.join(errors)}")
        return None

    def describe(self) -> dict:
        chat = self.candidates("chat")
        scan = self.candidates("scan")
        return {
            "available": [
                name for name, present in
                (("openai", self.settings.has_openai()), ("gemini", self.settings.has_gemini()))
                if present
            ],
            "chat": chat[0].describe() if chat else None,
            "scan": scan[0].describe() if scan else None,
        }


router = ModelRouter()
