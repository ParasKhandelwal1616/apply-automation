"""Short templated Wellfound note: fit line, one real metric, one company-specific detail."""
from __future__ import annotations

import re

from apply_bot.config import Profile
from apply_bot.models import JobPost

_METRIC_RE = re.compile(r"\d")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_BORING = re.compile(r"apply|salary|₹|\$|lpa|employees|series [a-h]|seed|remote|bengaluru|bangalore|hyderabad|chennai|full[\s-]?time|posted|ago|save", re.I)


def _metric(profile: Profile) -> str:
    for point in profile.proof_points:
        if _METRIC_RE.search(point):
            text = point.strip().rstrip(".")
            if ":" in text and len(text.split(":", 1)[0]) < 60:
                head, tail = text.split(":", 1)
                text = f"at {head.strip()}, {tail.strip()}"
            return text[:220]
    return ""


def _company_detail(post: JobPost) -> str:
    text = re.sub(r"\s+", " ", post.raw_text or "").strip()
    company = (post.company or "").strip()
    for sent in _SENT_RE.split(text):
        s = sent.strip()
        if 25 <= len(s) <= 160 and not _BORING.search(s) and s.lower() != (post.role or "").lower():
            return s.rstrip(".")
    return f"what {company or 'your team'} is building" if company else ""


def wellfound_note(profile: Profile, post: JobPost) -> str:
    role = (post.role or "this role").strip()
    company = (post.company or "").strip()
    greet = f"Hi {company} team" if company else "Hi team"
    company = company or "your team"
    first = f"{greet}, I'm applying for the {role} role; I build Python/FastAPI backends and AI/ML systems, which matches what you need."
    metric = _metric(profile)
    second = f"Recently, {metric[0].lower() + metric[1:]}." if metric else ""
    detail = _company_detail(post)
    third = f"I'm drawn to {company} because of this: {detail}." if detail and not detail.startswith("what ") else (
        f"I'd love to contribute to {detail}." if detail else "")
    return " ".join(x for x in (first, second, third) if x)
