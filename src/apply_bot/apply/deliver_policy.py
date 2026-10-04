from __future__ import annotations

import re

from apply_bot.models import FilterResult, JobPost

PREFIX_RE = re.compile(r"^\[(?:SEND|REVIEW)\]\s*")


def strip_verdict_prefix(subject: str) -> str:
    return PREFIX_RE.sub("", subject or "", count=1).strip()


def should_auto_send_email(post: JobPost, result: FilterResult, auto_send: bool) -> bool:
    if not auto_send:
        return False
    if result.verdict != "SEND":
        return False
    return bool(post.apply_email)
