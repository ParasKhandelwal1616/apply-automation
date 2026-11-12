from __future__ import annotations

import re

from apply_bot.config import Settings
from apply_bot.models import JobPost
from apply_bot.boards.rules import (
    experience_ok,
    is_consultancy,
    keyword_filter,
    mentions_fee_bond_training,
    size_ok,
    stage_ok,
)

INTERN_RE = re.compile(
    r"\bintern(?:ship)?\b|\bpart[\s-]?time\b|\bfreelance\b|\bcontract\b|\bwfh only intern\b",
    re.I,
)
FULL_TIME_RE = re.compile(r"full[\s-]?time|permanent", re.I)
ROLE_RE = re.compile(
    r"software|backend|\bsde\b|\bswe\b|python|machine learning|\bml\b|"
    r"\bai\b|genai|gen ai|\bllm\b|data engineer|applied scientist|full[\s-]?stack|\bdeveloper\b",
    re.I,
)
US_ONLY_RE = re.compile(
    r"us citizen|must be (?:a )?us|united states work authorization|"
    r"no sponsorship|cannot sponsor",
    re.I,
)
LPA_RE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(?:-|–|to)?\s*(\d+(?:\.\d+)?)?\s*"
    r"(?:lpa|lacs?|lakhs?|l\b)",
    re.I,
)
USD_RE = re.compile(
    r"\$\s*(\d+(?:\.\d+)?)\s*(k)?",
    re.I,
)
MONTHLY_INR_RE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*(\d{1,2}(?:,\d{2,3})+|\d{4,6})\s*(?:/|-)?\s*(?:per\s+)?(?:month|mo\b|pm\b)",
    re.I,
)
K_MONTH_RE = re.compile(
    r"(\d{2,3})\s*k\s*(?:/|-)?\s*(?:per\s+)?(?:month|mo\b|pm\b)",
    re.I,
)
STIPEND_INR_RE = re.compile(
    r"stipend\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*(\d{1,2}(?:,\d{2,3})+|\d{4,6})",
    re.I,
)
REMOTE_RE = re.compile(r"\bremote\b|work[\s-]?from[\s-]?home|\bwfh\b", re.I)
CITY_ALIASES = {
    "bengaluru": ("bengaluru", "bangalore", "bengaluru urban"),
    "hyderabad": ("hyderabad",),
    "chennai": ("chennai", "madras"),
    "gurugram": ("gurugram", "gurgaon"),
    "noida": ("noida",),
    "mumbai": ("mumbai", "bombay"),
    "pune": ("pune",),
    "delhi": ("delhi", "new delhi", "delhi ncr", "ncr"),
}


def _blob(post: JobPost) -> str:
    return f"{post.role or ''} {post.location or ''} {post.stipend or ''} {post.raw_text or ''} {post.apply_url or ''}"


def is_full_time(text: str) -> bool:
    if INTERN_RE.search(text) and not FULL_TIME_RE.search(text):
        return False
    if re.search(r"\bintern\b", text, re.I):
        return False
    return True


TITLE_NON_FT_RE = re.compile(
    r"\bintern(?:ship)?\b|\bcontract(?:or|ual)?\b|\bpart[\s-]?time\b|\bfreelance\b|\bapprentice(?:ship)?\b|\btemporary\b",
    re.I,
)
JOB_TYPE_FIELD_RE = re.compile(
    r"(?:employment\s*type|job\s*type|employment|type\s+of\s+job|engagement)\s*[:\-\u2013]\s*"
    r"(?:[a-z ,]*?)?(intern(?:ship)?|part[\s-]?time|contract(?:ual)?|freelance|temporary)\b",
    re.I,
)
JOB_TYPE_LEAD_RE = re.compile(r"^\W*(internship|contract|part[\s-]?time|freelance|temporary)\b", re.I)


def non_full_time_type(title: str, text: str) -> str | None:
    """Internship/contract judged ONLY from the job title or an explicit job-type field
    (e.g. 'Employment Type: Internship', or Wellfound's type label right after the title).
    Description text such as 'internship experience preferred' is ignored."""
    title = title or ""
    m = TITLE_NON_FT_RE.search(title)
    if m:
        return m.group(0).lower()
    m = JOB_TYPE_FIELD_RE.search(text or "")
    if m:
        return m.group(1).lower()
    rest = (text or "")
    if title and rest.lower().startswith(title.lower()):
        rest = rest[len(title):]
    m = JOB_TYPE_LEAD_RE.search(rest[:40])
    if m:
        return m.group(1).lower()
    return None


def max_experience_for(source: str, settings: Settings) -> int:
    return settings.wellfound_max_experience_years if source == "wellfound" else settings.board_max_experience_years


def location_ok(text: str, settings: Settings, *, allow_remote_india: bool) -> bool:
    lowered = text.lower()
    cities = settings.board_cities or ["bengaluru", "hyderabad", "chennai"]
    for city in cities:
        for alias in CITY_ALIASES.get(city.lower(), (city.lower(),)):
            if alias in lowered:
                return True
    if allow_remote_india and REMOTE_RE.search(lowered):
        return True
    # Pan-India / multi-city posts (e.g. Barclays) are OK — prefer BLR/HYD/CHN at form time.
    if re.search(r"pan[\s-]?india|anywhere in india|multiple locations|across india", lowered):
        return True
    return False


def _monthly_inr_values(text: str) -> list[float]:
    values: list[float] = []
    for match in MONTHLY_INR_RE.finditer(text):
        values.append(float(match.group(1).replace(",", "")))
    for match in K_MONTH_RE.finditer(text):
        values.append(float(match.group(1)) * 1000)
    for match in STIPEND_INR_RE.finditer(text):
        values.append(float(match.group(1).replace(",", "")))
    return values


def salary_ok(text: str, settings: Settings, *, usd: bool, min_lpa: float | None = None) -> tuple[bool, str]:
    """Missing salary is allowed. A listed amount at or below the floor is not."""
    floor = settings.min_ctc_lpa if min_lpa is None else min_lpa
    monthly_floor = settings.min_monthly_inr
    monthly = _monthly_inr_values(text)
    if monthly:
        if max(monthly) <= monthly_floor:
            return False, "monthly_below_min"
        return True, "monthly_ok"
    lpa_values: list[float] = []
    for match in LPA_RE.finditer(text):
        first = float(match.group(1))
        second = match.group(2)
        lpa_values.append(float(second) if second else first)
    if lpa_values:
        top = max(lpa_values)
        if top * 100000 / 12 <= monthly_floor or top < floor:
            return False, "ctc_below_min"
        return True, "ctc_ok"
    if usd:
        usd_values: list[float] = []
        for match in USD_RE.finditer(text):
            amount = float(match.group(1))
            if match.group(2):
                amount *= 1000
            usd_values.append(amount)
        if usd_values:
            if max(usd_values) < settings.min_salary_usd:
                return False, "usd_below_min"
            return True, "usd_ok"
    return True, "salary_unlisted"


def role_ok(text: str) -> bool:
    return bool(ROLE_RE.search(text))


def common_skip(text: str, company: str | None, settings: Settings, *, title: str = "", source: str = "naukri") -> str | None:
    kind = non_full_time_type(title, text)
    if kind:
        return f"not_full_time({kind})"
    if is_consultancy(text, company):
        return "consultancy"
    if mentions_fee_bond_training(text):
        return "fee_bond_training"
    max_years = max_experience_for(source, settings)
    if not experience_ok(text, max_years):
        return f"experience_gt_{max_years}y"
    return None


def recheck_full_jd(full_text: str, post: JobPost, settings: Settings, source: str = "naukri") -> tuple[bool, str]:
    """Re-apply the skip rules to the full job page (cards are truncated)."""
    if not full_text:
        return True, "ok"
    why = common_skip(full_text, post.company, settings, title=post.role or "", source=source)
    if why:
        return False, why
    return True, "ok"


def board_fit(post: JobPost, settings: Settings, *, source: str) -> tuple[bool, str]:
    text = _blob(post)
    why = common_skip(post.raw_text or text, post.company, settings, title=post.role or "", source=source)
    if why:
        return False, why
    if US_ONLY_RE.search(text) and source == "workatastartup":
        return False, "us_only"
    allow_remote = source in {"wellfound", "workatastartup"}
    if not location_ok(text, settings, allow_remote_india=allow_remote):
        return False, "location"
    if not role_ok(text):
        return False, "role"
    floor = settings.wellfound_min_lpa if source == "wellfound" else settings.min_ctc_lpa
    ok, why = salary_ok(text, settings, usd=allow_remote, min_lpa=floor)
    if not ok:
        return False, why
    kw_ok, kw_why = keyword_filter(post.role or "", text, settings.board_keyword_groups, settings.board_title_excludes)
    if not kw_ok:
        return False, kw_why
    if source == "wellfound":
        if not stage_ok(text, settings.wellfound_min_stage):
            return False, "stage_below_series_a"
        if not size_ok(text, settings.wellfound_size_min, settings.wellfound_size_max):
            return False, "company_size"
    return True, "ok"
