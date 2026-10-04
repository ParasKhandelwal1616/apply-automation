from __future__ import annotations

import json
import re
from pathlib import Path

from apply_bot.config import Settings
from apply_bot.models import JobPost
from apply_bot.parse.regex import (
    EMAIL_RE,
    batch_includes_2027,
    classify_method,
    parse_job_regex,
)

JSON_SCHEMA_HINT = """
Return ONLY a JSON object with keys:
company, role, batch_raw, stipend, location, apply_email, apply_url, requirements (array of strings).
Use null when a field is not present in the source. Never invent an email or URL.
"""


def email_looks_garbled(email: str | None) -> bool:
    if not email:
        return False
    if not EMAIL_RE.fullmatch(email):
        return True
    host = email.rsplit("@", 1)[-1].lower()
    suspicious = ("gmai1", "gmial", "gmal.com", "yahooo", "outlok")
    return any(s in host for s in suspicious)


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _job_from_gemini(data: dict, raw_text: str, fingerprint: str, source: str) -> JobPost:
    email = data.get("apply_email") or None
    url = data.get("apply_url") or None
    if email:
        email = str(email).strip().lower()
    if url:
        url = str(url).strip()
    company = data.get("company") or None
    role = data.get("role") or None
    batch_raw = data.get("batch_raw") or None
    reqs = data.get("requirements") or []
    if not isinstance(reqs, list):
        reqs = []
    careers = bool(url) and "form" not in (url or "").lower()
    return JobPost(
        company=str(company).strip() if company else None,
        role=str(role).strip() if role else None,
        batch_raw=str(batch_raw).strip() if batch_raw else None,
        batch_includes_2027=batch_includes_2027(str(batch_raw or raw_text)),
        stipend=(str(data["stipend"]).strip() if data.get("stipend") else None),
        location=(str(data["location"]).strip() if data.get("location") else None),
        apply_method=classify_method(email, url, careers),
        apply_email=email,
        apply_url=url,
        requirements=[str(r) for r in reqs],
        raw_text=raw_text,
        source_fingerprint=fingerprint,
        parse_source=source,  # type: ignore[arg-type]
        email_looks_garbled=email_looks_garbled(email),
    )


def _client(settings: Settings):
    if not settings.gemini_api_key:
        return None
    from google import genai

    return genai.Client(api_key=settings.gemini_api_key)


def parse_with_gemini_text(text: str, fingerprint: str, settings: Settings) -> JobPost | None:
    client = _client(settings)
    if client is None:
        return None
    prompt = (
        "Extract a job referral posting into JSON.\n"
        f"{JSON_SCHEMA_HINT}\n\nSOURCE:\n{text}"
    )
    try:
        response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
    except Exception as exc:
        print(f"Gemini text parse failed: {exc}")
        return None
    data = _parse_json_object(getattr(response, "text", "") or "")
    if not data:
        return None
    return _job_from_gemini(data, text, fingerprint, "gemini_text")


def parse_with_gemini_vision(image_path: Path, fingerprint: str, settings: Settings) -> JobPost | None:
    client = _client(settings)
    if client is None:
        return None
    from google.genai import types

    blob = image_path.read_bytes()
    prompt = "Read this Telegram job-post screenshot and extract JSON.\n" + JSON_SCHEMA_HINT
    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Part.from_bytes(data=blob, mime_type="image/png"),
                prompt,
            ],
        )
    except Exception as exc:
        print(f"Gemini vision parse failed: {exc}")
        return None
    data = _parse_json_object(getattr(response, "text", "") or "")
    if not data:
        return None
    return _job_from_gemini(data, f"[vision:{image_path.name}]", fingerprint, "gemini_vision")


def parse_job(
    text: str,
    fingerprint: str,
    settings: Settings,
    hrefs: list[str] | None = None,
    screenshot_path: str | None = None,
    needs_vision: bool = False,
) -> JobPost:
    regex_post = parse_job_regex(text, fingerprint, hrefs=hrefs)
    if not settings.use_gemini or not settings.gemini_api_key:
        return regex_post
    missing_core = not regex_post.company or (
        not regex_post.apply_email and not regex_post.apply_url
    )
    if not missing_core and not needs_vision:
        return regex_post
    if needs_vision and screenshot_path:
        vision = parse_with_gemini_vision(Path(screenshot_path), fingerprint, settings)
        if vision:
            if not vision.raw_text or vision.raw_text.startswith("[vision:"):
                vision.raw_text = text or vision.raw_text
            return vision
    if missing_core and text.strip():
        gem = parse_with_gemini_text(text, fingerprint, settings)
        if gem:
            if not gem.apply_email and regex_post.apply_email:
                gem.apply_email = regex_post.apply_email
            if not gem.apply_url and regex_post.apply_url:
                gem.apply_url = regex_post.apply_url
            return gem
    return regex_post
