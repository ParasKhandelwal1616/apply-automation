from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import Page

from apply_bot.boards.base import blocked_reason, page_text
from apply_bot.config import Settings
from apply_bot.models import JobPost

NAUKRI_CITIES = {
    "bengaluru": "bangalore",
    "bangalore": "bangalore",
    "hyderabad": "hyderabad",
    "chennai": "chennai",
}


def naukri_filter_params(settings: Settings, job_age: int | None = None) -> str:
    """URL filters verified on naukri.com (Oct 2026): experience, jobAge, ctcFilter (repeatable),
    jobPostType=1 (company-posted only), sort=f (newest first)."""
    parts = [f"experience={settings.naukri_experience}"]
    age = settings.naukri_job_age_days if job_age is None else job_age
    if age:
        parts.append(f"jobAge={age}")
    parts += [f"ctcFilter={c}" for c in settings.naukri_ctc_filters]
    if settings.naukri_company_posted_only:
        parts.append("jobPostType=1")
    if settings.naukri_sort_by_date:
        parts.append("sort=f")
    return "&".join(parts)


def naukri_search_url(settings: Settings, query: str, city: str, job_age: int | None = None) -> str:
    """One Naukri search: a single role query in a single city (no combined/boolean queries)."""
    city = NAUKRI_CITIES.get(city.lower(), city.lower())
    return (
        "https://www.naukri.com/"
        f"{quote_plus(query).replace('+', '-')}-jobs-in-{city}"
        f"?k={quote_plus(query)}&l={quote_plus(city)}&{naukri_filter_params(settings, job_age)}"
    )


def naukri_searches(settings: Settings) -> list[tuple[str, str]]:
    """(query, city) pairs in run order: each query separately, city by city."""
    return [(q, c) for q in settings.board_queries for c in settings.board_cities]


def naukri_search_urls(settings: Settings, job_age: int | None = None) -> list[str]:
    cities = [NAUKRI_CITIES.get(c.lower(), c.lower()) for c in settings.board_cities]
    filters = naukri_filter_params(settings, job_age)
    urls: list[str] = []
    for query in settings.board_queries:
        slug = quote_plus(query)
        for city in cities:
            urls.append(
                "https://www.naukri.com/"
                f"{quote_plus(query).replace('+', '-')}-jobs-in-{city}"
                f"?k={slug}&l={quote_plus(city)}&{filters}"
            )
    return urls


WELLFOUND_CITIES = {"bengaluru": "bangalore", "bangalore": "bangalore", "hyderabad": "hyderabad", "chennai": "chennai"}


def wellfound_search_urls(settings: Settings) -> list[str]:
    """Role pages per city, plus the remote page (cards are then checked for 'India')."""
    cities = [WELLFOUND_CITIES.get(c.lower(), c.lower()) for c in settings.board_cities]
    urls = []
    for role in settings.wellfound_roles:
        for city in cities:
            urls.append(f"https://wellfound.com/role/l/{role}/{city}")
        if settings.wellfound_include_remote_india:
            urls.append(f"https://wellfound.com/role/r/{role}")
    return urls


def workatastartup_search_urls(settings: Settings) -> list[str]:
    urls = []
    for query in settings.board_queries:
        urls.append(f"https://www.workatastartup.com/jobs?query={quote_plus(query)}")
    return urls


WELLFOUND_JOB_PATH_RE = re.compile(r"^(?:/company/[^/]+)?/jobs/\d+-[^/]+/?$")
WAAS_JOB_PATH_RE = re.compile(r"^/(?:jobs|companies/[^/]+/jobs)/\d+(?:-[^/]*)?/?$")


def is_job_url(source: str, href: str) -> bool:
    """Only real job pages count as cards. Wellfound menu pages such as /jobs, /jobs/home or
    /jobs/applications are rejected; a job page looks like /jobs/<numeric id>-<slug>."""
    try:
        parsed = urlparse(href or "")
    except ValueError:
        return False
    host, path = parsed.netloc.lower(), parsed.path
    if source == "wellfound":
        return host.endswith("wellfound.com") and bool(WELLFOUND_JOB_PATH_RE.match(path))
    if source == "workatastartup":
        return host.endswith("workatastartup.com") and bool(WAAS_JOB_PATH_RE.match(path))
    if source == "naukri":
        return host.endswith("naukri.com") and path.startswith("/job-listings-")
    return True


def _cards_from_links(page: Page, host_part: str, limit: int) -> list[dict[str, str]]:
    raw = page.evaluate(
        """(host) => {
          const out = [];
          const seen = new Set();
          for (const a of document.querySelectorAll('a[href]')) {
            const href = a.href || '';
            if (!href.includes(host)) continue;
            if (seen.has(href)) continue;
            const card = a.closest('.srp-jobtuple-wrapper, .cust-job-tuple, article, .jobTuple, [data-job-id], [class*="JobCard"], [class*="job-tuple"], [class*="jobTuple"], li') || a.closest('article, [class*="tuple"]') || a.parentElement?.parentElement || a;
            const text = (card.innerText || a.innerText || '').replace(/\\s+/g, ' ').trim();
            if (text.length < 20) continue;
            seen.add(href);
            const pick = (sels) => { for (const s of sels) { const e = card.querySelector(s); if (e && (e.innerText || '').trim()) return e.innerText.trim(); } return ''; };
            const title = pick(['a.title', '.title', 'h2 a', 'h2', '[class*="JobTitle"]', '[class*="jobTitle"]']) || (a.innerText || '').trim();
            const company = pick(['.comp-name', 'a.comp-name', '[class*="comp-name"]', '[class*="companyName"]', '[class*="CompanyName"]', 'h2 + div a', '[class*="startup"] h2']);
            const salary = pick(['.sal-wrap span', '.sal', '[class*="salary"]', '[class*="compensation"]']);
            const loc = pick(['.locWdth', '.loc-wrap', '[class*="location"]']);
            out.push({ href, text: text.slice(0, 800), title: title.slice(0, 140), company: company.slice(0, 120), salary: salary.slice(0, 60), loc: loc.slice(0, 120) });
            if (out.length >= 40) break;
          }
          return out;
        }""",
        host_part,
    )
    return list(raw)[:limit]


def collect_cards(page: Page, urls: list[str], host_part: str, limit: int) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for url in urls:
        if len(found) >= limit:
            break
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)
        reason = blocked_reason(page_text(page))
        if reason:
            raise RuntimeError(reason)
        for card in _cards_from_links(page, host_part, limit):
            href = card["href"]
            if href in seen:
                continue
            seen.add(href)
            found.append(card)
            if len(found) >= limit:
                break
    return found


def card_to_post(card: dict[str, str], source: str) -> JobPost:
    text = card.get("text") or ""
    lines = [line.strip() for line in text.split("  ") if line.strip()]
    role = (card.get("title") or "").strip() or (lines[0][:120] if lines else None)
    company = (card.get("company") or "").strip() or (lines[1][:120] if len(lines) > 1 else None)
    return JobPost(
        company=company,
        role=role,
        location=(card.get("loc") or "").strip() or text[:240],
        stipend=None,
        apply_method=source,  # type: ignore[arg-type]
        apply_url=card["href"],
        raw_text=text,
        source_fingerprint=f"{source}:{card['href']}",
        batch_includes_2027=True,
    )
