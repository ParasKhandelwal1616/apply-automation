from __future__ import annotations

import base64
import json
import urllib.request

from apply_bot.config import Settings

GROK_URL = "https://api.x.ai/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"


def chat_endpoint(api_key: str, model: str) -> tuple[str, str]:
    """GROK_API_KEY may hold an xAI key (xai-...) or a Groq key (gsk_...).
    Groq keys are rejected by api.x.ai with HTTP 400, so send them to Groq,
    swapping a grok-* model name (which Groq does not host) for a Groq model."""
    if api_key.startswith("gsk_"):
        if not model or model.lower().startswith("grok"):
            model = GROQ_DEFAULT_MODEL
        return GROQ_URL, model
    return GROK_URL, model


def providers(settings: Settings) -> list[str]:
    names: list[str] = []
    if settings.use_grok and settings.grok_api_key:
        names.append("grok")
    if settings.use_gemini and settings.gemini_api_key:
        names.append("gemini")
    return names


def llm_enabled(settings: Settings) -> bool:
    return bool(providers(settings))


def complete_text(settings: Settings, prompt: str) -> tuple[str, str] | None:
    for name in providers(settings):
        try:
            text = _grok_text(settings, prompt) if name == "grok" else _gemini_text(settings, prompt)
        except Exception as exc:
            print(f"{name} request failed: {exc}")
            continue
        if text and text.strip():
            return name, text
    return None


def complete_vision(settings: Settings, png: bytes, prompt: str) -> tuple[str, str] | None:
    for name in providers(settings):
        try:
            text = (
                _grok_vision(settings, png, prompt)
                if name == "grok"
                else _gemini_vision(settings, png, prompt)
            )
        except Exception as exc:
            print(f"{name} vision failed: {exc}")
            continue
        if text and text.strip():
            return name, text
    return None


def _grok_text(settings: Settings, prompt: str) -> str:
    return _grok(settings, prompt)


def _grok_vision(settings: Settings, png: bytes, prompt: str) -> str:
    encoded = base64.b64encode(png).decode("ascii")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
    ]
    return _grok(settings, content)


def _grok(settings: Settings, content) -> str:
    url, model = chat_endpoint(settings.grok_api_key, settings.grok_model)
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": content}],
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.grok_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "apply-bot/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode())
    return str(payload["choices"][0]["message"]["content"] or "")


def _gemini_text(settings: Settings, prompt: str) -> str:
    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
    return getattr(response, "text", "") or ""


def _gemini_vision(settings: Settings, png: bytes, prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[types.Part.from_bytes(data=png, mime_type="image/png"), prompt],
    )
    return getattr(response, "text", "") or ""
