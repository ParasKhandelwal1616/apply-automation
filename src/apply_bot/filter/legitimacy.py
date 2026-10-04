from __future__ import annotations

import re

from apply_bot.config import Settings
from apply_bot.models import FilterResult, JobPost

STOP_TOKENS = {
    "ai",
    "pvt",
    "ltd",
    "llc",
    "inc",
    "llp",
    "the",
    "and",
    "group",
    "labs",
    "lab",
    "technologies",
    "technology",
    "systems",
    "solutions",
    "media",
    "apps",
}


def _email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].lower()


def _is_personal(domain: str | None, settings: Settings) -> bool:
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) for d in settings.personal_email_domains)


def _company_tokens(company: str | None) -> set[str]:
    if not company:
        return set()
    parts = re.findall(r"[a-z0-9]+", company.lower())
    return {p for p in parts if len(p) > 2 and p not in STOP_TOKENS}


def domain_matches_company(company: str | None, email: str | None) -> bool:
    domain = _email_domain(email)
    if not domain or not company:
        return False
    tokens = _company_tokens(company)
    if not tokens:
        compact = re.sub(r"[^a-z0-9]", "", company.lower())
        host = domain.split(".")[0]
        return len(compact) >= 4 and compact in domain.replace(".", "")
    host = domain.replace(".", "")
    return any(token in host or token in domain for token in tokens)


def _is_famous_brand(company: str | None, settings: Settings) -> bool:
    if not company:
        return False
    name = company.lower()
    return any(brand in name for brand in settings.famous_brands)


def _is_careers_url(url: str | None, settings: Settings) -> bool:
    if not url:
        return False
    lowered = url.lower()
    if "forms.gle" in lowered or "docs.google.com/forms" in lowered:
        return False
    return any(marker.lower() in lowered for marker in settings.careers_url_markers)


def _stipend_suspicious(stipend: str | None) -> bool:
    if not stipend:
        return False
    dollar = re.search(r"\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)", stipend)
    if dollar:
        amount = float(dollar.group(1).replace(",", ""))
        if amount <= 500:
            return True
    return False


def verdict_for(post: JobPost, settings: Settings) -> FilterResult:
    email = post.apply_email
    domain = _email_domain(email)
    personal = _is_personal(domain, settings)
    brand = _is_famous_brand(post.company, settings)

    if post.email_looks_garbled:
        return FilterResult(verdict="REVIEW", reason="garbled_email", relevant=True)

    if brand and personal:
        return FilterResult(verdict="SKIP", reason="brand_plus_personal_email", relevant=True)

    if not post.company and post.apply_url:
        return FilterResult(verdict="SKIP", reason="nameless_form", relevant=True)

    if _stipend_suspicious(post.stipend):
        return FilterResult(verdict="REVIEW", reason="stipend_suspicious", relevant=True)

    if post.apply_method == "careers" or _is_careers_url(post.apply_url, settings):
        if not email:
            return FilterResult(verdict="REVIEW", reason="careers_page", relevant=True)

    if personal:
        return FilterResult(verdict="REVIEW", reason="personal_email", relevant=True)

    if email and not domain_matches_company(post.company, email):
        return FilterResult(verdict="REVIEW", reason="domain_mismatch", relevant=True)

    if email and domain_matches_company(post.company, email):
        return FilterResult(verdict="SEND", reason="company_domain", relevant=True)

    if post.apply_method in {"google_form", "email_and_form"} and post.company:
        return FilterResult(verdict="REVIEW", reason="form_needs_click", relevant=True)

    if post.apply_url or email:
        return FilterResult(verdict="REVIEW", reason="uncertain_contact", relevant=True)

    return FilterResult(verdict="SKIP", reason="no_apply_target", relevant=True)
