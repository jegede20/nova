"""Pluggable AI providers.

Nova talks to one small interface (`AIProvider`). Swapping OpenAI for Anthropic,
Groq, Ollama or any OpenAI-compatible endpoint is a settings change, not a
rewrite. All providers speak the same message/tool-call shape.
"""

from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..core.logging_setup import get_logger

log = get_logger("ai")


class AIError(Exception):
    """Raised for provider failures. Message is safe to show the user."""


class AIUnavailable(AIError):
    """Network down / no key / service unreachable -> Nova falls back to local mode."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AIResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class AIProvider(ABC):
    name = "base"
    supports_vision = False

    def __init__(self, api_key: str | None, model: str, base_url: str = "", temperature: float = 0.2) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.temperature = temperature

    @abstractmethod
    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   timeout: float = 60.0) -> AIResponse: ...

    async def describe_image(self, image_b64: str, prompt: str, timeout: float = 60.0) -> str:
        raise AIError(f"{self.name} cannot analyse images.")

    def available(self) -> bool:
        return bool(self.api_key) or bool(self.base_url)


# ---------------------------------------------------------------- OpenAI-style
class OpenAIProvider(AIProvider):
    """Works with OpenAI and any OpenAI-compatible server (Groq, Ollama, LM Studio, vLLM)."""

    name = "openai"
    supports_vision = True
    DEFAULT_URL = "https://api.openai.com/v1"

    def _url(self, path: str) -> str:
        return f"{self.base_url or self.DEFAULT_URL}{path}"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   timeout: float = 60.0) -> AIResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data = await _post_json(self._url("/chat/completions"), payload, self._headers(), timeout)
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise AIError("The AI service returned an unexpected response.") from e

        calls = []
        for tc in choice.get("tool_calls") or []:
            fn = tc.get("function", {})
            calls.append(ToolCall(tc.get("id", fn.get("name", "")), fn.get("name", ""),
                                  _safe_json(fn.get("arguments"))))
        return AIResponse(text=choice.get("content") or "", tool_calls=calls, raw=data)

    async def describe_image(self, image_b64: str, prompt: str, timeout: float = 60.0) -> str:
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }],
            "max_tokens": 700,
        }
        data = await _post_json(self._url("/chat/completions"), payload, self._headers(), timeout)
        return data["choices"][0]["message"].get("content", "")


# ---------------------------------------------------------------- Anthropic
class AnthropicProvider(AIProvider):
    name = "anthropic"
    supports_vision = True
    DEFAULT_URL = "https://api.anthropic.com/v1"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
        }

    @staticmethod
    def _convert(messages: list[dict]) -> tuple[str, list[dict]]:
        """OpenAI-shaped messages -> Anthropic system + messages."""
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                system_parts.append(m.get("content", ""))
            elif role == "tool":
                out.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                }]})
            elif role == "assistant" and m.get("tool_calls"):
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": _safe_json(tc["function"]["arguments"]),
                    })
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": str(role or "user"), "content": m.get("content", "")})
        return "\n".join(system_parts), out

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   timeout: float = 60.0) -> AIResponse:
        system, msgs = self._convert(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "max_tokens": 2048,
            "temperature": self.temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [{
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            } for t in tools]
        data = await _post_json(f"{self.base_url or self.DEFAULT_URL}/messages", payload, self._headers(), timeout)
        text, calls = "", []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(block.get("id", ""), block.get("name", ""), block.get("input", {})))
        return AIResponse(text=text, tool_calls=calls, raw=data)

    async def describe_image(self, image_b64: str, prompt: str, timeout: float = 60.0) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 700,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": prompt},
            ]}],
        }
        data = await _post_json(f"{self.base_url or self.DEFAULT_URL}/messages", payload, self._headers(), timeout)
        return "".join(b.get("text", "") for b in data.get("content", []))


# ---------------------------------------------------------------- Ollama (local)
class OllamaProvider(OpenAIProvider):
    """Fully local models via Ollama's OpenAI-compatible API. No API key needed."""

    name = "ollama"
    DEFAULT_URL = "http://localhost:11434/v1"

    def available(self) -> bool:
        return True


PROVIDERS: dict[str, type[AIProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "groq": OpenAIProvider,
    "ollama": OllamaProvider,
    "custom": OpenAIProvider,
}

PROVIDER_DEFAULTS = {
    "openai": {"base_url": "", "model": "gpt-4o-mini"},
    "anthropic": {"base_url": "", "model": "claude-3-5-sonnet-20241022"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    "custom": {"base_url": "", "model": ""},
}


def build_provider(settings: Any) -> AIProvider:
    key = str(settings.get("ai_provider", "openai")).lower()
    cls = PROVIDERS.get(key, OpenAIProvider)
    defaults = PROVIDER_DEFAULTS.get(key, {})
    base_url = settings.get("ai_base_url", "") or defaults.get("base_url", "")
    model = settings.get("ai_model", "") or defaults.get("model", "")
    api_key = settings.api_key_for(key) if hasattr(settings, "api_key_for") else None
    return cls(api_key, model, base_url, float(settings.get("ai_temperature", 0.2)))


def build_vision_provider(settings: Any) -> AIProvider:
    base = build_provider(settings)
    vision_model = settings.get("vision_model", "") or base.model
    return type(base)(base.api_key, vision_model, base.base_url, base.temperature)


# ---------------------------------------------------------------- helpers
async def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.ConnectError as e:
        raise AIUnavailable("I can't reach the AI service. Check your internet connection.") from e
    except httpx.TimeoutException as e:
        raise AIUnavailable("The AI service took too long to respond.") from e
    except httpx.HTTPError as e:
        raise AIUnavailable(f"Network problem talking to the AI service: {type(e).__name__}") from e

    if resp.status_code == 401:
        raise AIError("The AI provider rejected the API key. Check it in Settings.")
    if resp.status_code == 429:
        raise AIUnavailable("The AI service is rate limiting us. Try again shortly.")
    if resp.status_code >= 500:
        raise AIUnavailable("The AI service is having problems right now.")
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")[:200]
        except Exception:
            pass
        raise AIError(f"The AI request failed ({resp.status_code}). {detail}".strip())
    try:
        return resp.json()
    except json.JSONDecodeError as e:
        raise AIError("The AI service sent a response Nova couldn't read.") from e


def _safe_json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (json.JSONDecodeError, TypeError):
        log.warning("Could not parse tool arguments from the model.")
        return {}


def encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")
