from __future__ import annotations

import re

from apply_bot.models import ApplyMethod, JobPost

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
FORM_RE = re.compile(
    r"https?://(?:docs\.google\.com/forms/[^\s]+|forms\.gle/[^\s]+)",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
LABEL_RE = re.compile(
    r"^(?:company|role|batch|stipend|location|how\s+to\s+apply|apply)\s*[-–—:]\s*(.+)$",
    re.I,
)

BATCH_2027_RE = re.compile(
    r"2027|20?26\s*[/\-–]\s*27|20?25\s*[/\-–]\s*20?26\s*[/\-–]\s*20?27",
    re.I,
)


def batch_includes_2027(text: str | None) -> bool:
    if not text:
        return False
    return bool(BATCH_2027_RE.search(text))


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().strip("-: ")


def _field(text: str, name: str) -> str | None:
    pattern = re.compile(
        rf"^{re.escape(name)}\s*[-–—:]\s*(.+)$",
        re.I | re.M,
    )
    match = pattern.search(text)
    if not match:
        return None
    return _clean(match.group(1))


def _first_email(text: str) -> str | None:
    match = EMAIL_RE.search(text)
    return match.group(0).lower() if match else None


def _apply_url(text: str) -> str | None:
    form = FORM_RE.search(text)
    if form:
        return form.group(0).rstrip(").,]")
    urls = [u.rstrip(").,]") for u in URL_RE.findall(text)]
    return urls[0] if urls else None


def classify_method(email: str | None, url: str | None, careers: bool) -> ApplyMethod:
    if careers and url and not email:
        return "careers"
    if email and url:
        return "email_and_form" if not careers else "email_and_form"
    if email:
        return "email"
    if url and careers:
        return "careers"
    if url:
        return "google_form" if _is_form_url(url) else "careers"
    return "unknown"


def _is_form_url(url: str) -> bool:
    lowered = url.lower()
    return "forms.gle" in lowered or "docs.google.com/forms" in lowered


def _is_careers_url(url: str | None, markers: list[str] | None = None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    if _is_form_url(lowered):
        return False
    default = [
        "greenhouse.io",
        "lever.co",
        "myworkday.com",
        "workday.com",
        "ashbyhq.com",
        "careers.",
        "linkedin.com/jobs",
        "wellfound.com",
    ]
    for marker in markers or default:
        if marker.lower() in lowered:
            return True
    if "/jobs" in lowered or "careers" in lowered:
        return True
    return False


def parse_job_regex(text: str, source_fingerprint: str, hrefs: list[str] | None = None) -> JobPost:
    hrefs = hrefs or []
    combined = text + "\n" + "\n".join(hrefs)
    company = _field(text, "Company")
    role = _field(text, "Role")
    batch_raw = _field(text, "Batch")
    stipend = _field(text, "Stipend")
    location = _field(text, "Location")

    apply_email = _first_email(combined)
    apply_url = None
    mailto = next((h[7:] for h in hrefs if h.lower().startswith("mailto:")), None)
    if mailto:
        apply_email = apply_email or mailto.split("?")[0].lower()
    for href in hrefs:
        if href.lower().startswith("mailto:"):
            continue
        apply_url = href
        if _is_form_url(href):
            break
    if not apply_url:
        apply_url = _apply_url(combined)

    careers = _is_careers_url(apply_url)
    method = classify_method(apply_email, apply_url, careers)
    reqs = [
        _clean(line.lstrip("-•* "))
        for line in text.splitlines()
        if line.strip().startswith(("-", "•", "*"))
    ]

    return JobPost(
        company=company,
        role=role,
        batch_raw=batch_raw,
        batch_includes_2027=batch_includes_2027(batch_raw or text),
        stipend=stipend,
        location=location,
        apply_method=method,
        apply_email=apply_email,
        apply_url=apply_url,
        requirements=reqs,
        raw_text=text,
        source_fingerprint=source_fingerprint,
        parse_source="regex",
    )
