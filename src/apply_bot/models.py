from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


ParseSource = Literal["regex", "gemini_text", "gemini_vision"]
ApplyMethod = Literal["email", "google_form", "careers", "email_and_form", "unknown"]
Verdict = Literal["SEND", "REVIEW", "SKIP"]


class ExtractedMessage(BaseModel):
    fingerprint: str
    text: str = ""
    hrefs: list[str] = Field(default_factory=list)
    screenshot_path: str | None = None
    needs_vision: bool = False
    preview: str = ""


class JobPost(BaseModel):
    company: str | None = None
    role: str | None = None
    batch_raw: str | None = None
    batch_includes_2027: bool = False
    stipend: str | None = None
    location: str | None = None
    apply_method: ApplyMethod = "unknown"
    apply_email: str | None = None
    apply_url: str | None = None
    requirements: list[str] = Field(default_factory=list)
    raw_text: str = ""
    source_fingerprint: str
    parse_source: ParseSource = "regex"
    email_looks_garbled: bool = False


class FilterResult(BaseModel):
    verdict: Verdict
    reason: str
    relevant: bool = True


class ApplicationDraft(BaseModel):
    subject: str
    body: str
    form_answers: dict[str, str] = Field(default_factory=dict)


class ProcessStatus(str, Enum):
    DRAFT_CREATED = "draft_created"
    FORM_PREPARED = "form_prepared"
    CAREERS_OPENED = "careers_opened"
    EMAIL_SENT = "email_sent"
    FORM_SUBMITTED = "form_submitted"
    SKIPPED = "skipped"
    SEEN = "seen"
