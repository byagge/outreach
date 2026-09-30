"""LLM клиент: OpenAI / OpenRouter / Groq / Ollama + нативный Anthropic."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


class LlmError(RuntimeError):
    pass


def _is_anthropic(base: str) -> bool:
    b = (base or "").lower()
    return "anthropic.com" in b or b.rstrip("/").endswith("/anthropic")


def _headers(api_key: str = "", *, anthropic: bool = False) -> dict[str, str]:
    cfg = get_settings()
    key = api_key or cfg.llm_api_key
    if anthropic:
        h = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if key:
            h["x-api-key"] = key
        return h
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    base = (cfg.llm_base_url or "").lower()
    if "openrouter" in base:
        h["HTTP-Referer"] = cfg.api_public_url or "https://outreach.local"
        h["X-Title"] = "Outreach Premium Qualifier"
    return h


async def _anthropic_messages(
    messages: list[dict[str, str]],
    *,
    model: str,
    api_key: str,
    base: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str:
    system = ""
    converted: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content") or ""
        if role == "system":
            system = (system + "\n" + content).strip() if system else content
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        converted.append({"role": role, "content": content})
    if not converted:
        converted = [{"role": "user", "content": "ping"}]
    url = base.rstrip("/")
    if not url.endswith("/v1/messages") and not url.endswith("/messages"):
        url = url.rstrip("/") + "/v1/messages"
    payload: dict[str, Any] = {
        "model": model,
        "messages": converted,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=_headers(api_key, anthropic=True), json=payload)
    if r.status_code >= 400:
        raise LlmError(f"Anthropic HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    blocks = data.get("content") or []
    texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    out = "\n".join(t for t in texts if t).strip()
    if not out:
        raise LlmError(f"Anthropic пустой ответ: {str(data)[:300]}")
    return out


async def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 1200,
    timeout: float | None = None,
    base_url: str = "",
    model: str = "",
    api_key: str = "",
) -> str:
    """Chat API: OpenAI-compatible или Anthropic Messages."""
    cfg = get_settings()
    base = (base_url or cfg.llm_base_url or "").rstrip("/")
    mdl = model or cfg.llm_model
    key = api_key or cfg.llm_api_key
    if not base:
        raise LlmError("LLM_BASE_URL не задан")
    if not mdl:
        raise LlmError("LLM_MODEL не задан")
    if not key and "11434" not in base and "localhost" not in base:
        raise LlmError("LLM_API_KEY не задан")
    to = timeout if timeout is not None else float(cfg.llm_timeout)

    if _is_anthropic(base):
        return await _anthropic_messages(
            messages,
            model=mdl,
            api_key=key,
            base=base,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=to,
        )

    url = f"{base}/chat/completions"
    payload: dict[str, Any] = {
        "model": mdl,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=to) as client:
        try:
            r = await client.post(url, headers=_headers(key), json=payload)
        except httpx.HTTPError as e:
            raise LlmError(f"LLM сеть: {e}") from e
    if r.status_code >= 400:
        raise LlmError(f"LLM HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise LlmError(f"LLM странный ответ: {str(data)[:300]}") from e


def extract_json(text: str) -> Any:
    raw = (text or "").strip()
    if not raw:
        raise LlmError("пустой ответ LLM")
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    start_obj = raw.find("{")
    start_arr = raw.find("[")
    if start_obj < 0 and start_arr < 0:
        raise LlmError(f"нет JSON: {raw[:200]}")
    if start_arr >= 0 and (start_obj < 0 or start_arr < start_obj):
        start = start_arr
        end = raw.rfind("]") + 1
    else:
        start = start_obj
        end = raw.rfind("}") + 1
    blob = raw[start:end]
    try:
        return json.loads(blob)
    except json.JSONDecodeError as e:
        raise LlmError(f"JSON parse: {e}; {blob[:200]}") from e


def llm_configured() -> bool:
    cfg = get_settings()
    return bool(cfg.llm_enabled and cfg.llm_base_url and cfg.llm_model and cfg.llm_api_key) or bool(
        cfg.llm_enabled
        and cfg.llm_base_url
        and cfg.llm_model
        and ("11434" in cfg.llm_base_url or "localhost" in cfg.llm_base_url)
    )


async def llm_available() -> tuple[bool, str]:
    if not llm_configured():
        return False, "Нужны LLM_ENABLED + LLM_BASE_URL + LLM_MODEL + LLM_API_KEY"
    cfg = get_settings()
    try:
        await chat_completion(
            [{"role": "user", "content": 'Reply with exactly: {"ok":true}'}],
            max_tokens=32,
            timeout=min(30.0, float(cfg.llm_timeout)),
        )
        return True, cfg.llm_model
    except Exception as e:
        return False, str(e)[:240]
