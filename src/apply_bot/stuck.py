from __future__ import annotations

from apply_bot.models import JobPost

STUCK_HOSTS = (
    "internshala.com",
    "myworkdayjobs.com",
    "workday.com",
    "greenhouse.io",
    "youform.com",
    "keka.com",
    "careerpuck.com",
    "forms.cloud.microsoft",
)

STUCK_REASONS = frozenset(
    {
        "stuck_ats",
        "skip_ragaai",
        "needs_login",
        "extra_step",
        "stuck_picker",
    }
)


def stuck_reason(
    company: str | None = None,
    role: str | None = None,
    url: str | None = None,
    reason: str | None = None,
) -> str | None:
    company_l = (company or "").lower()
    role_l = (role or "").lower()
    url_l = (url or "").lower()
    reason_l = (reason or "").lower()
    if "ragaai" in company_l or "customer success" in role_l:
        return "skip_ragaai"
    if "infobip" in company_l:
        return "stuck_picker"
    if any(host in url_l for host in STUCK_HOSTS):
        return "stuck_ats"
    if reason_l in STUCK_REASONS:
        return reason_l
    if "video" in reason_l:
        return "skip_ragaai" if "ragaai" in company_l else "stuck_ats"
    if "needs_login" in reason_l or reason_l == "extra_step":
        return reason_l if reason_l in STUCK_REASONS else "needs_login"
    return None


def opening_is_stuck(post: JobPost, reason: str | None = None) -> str | None:
    return stuck_reason(post.company, post.role, post.apply_url, reason)


def completable_method(method: str | None) -> bool:
    return (method or "") in {"email", "google_form", "email_and_form"}
