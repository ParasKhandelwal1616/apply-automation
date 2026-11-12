"""Skip rules for job-board cards (Naukri / Wellfound). Pure functions, no browser."""
from __future__ import annotations

import re

CONSULTANCY_RE = re.compile(
    r"\bconsultan(?:cy|ts?)\b|\bstaffing\b|\bmanpower\b|\bplacements?\b|\brecruit(?:ment|ers?|ing) (?:services|solutions|agency|firm)\b|"
    r"\bhr (?:services|solutions|consult\w*)\b|\btalent (?:solutions|services)\b|\boutsourcing\b|"
    r"hiring (?:on behalf of|for (?:our|a|one of our) client)|\bfor (?:our|a) client\b|\bclient of ours\b|\bthird[\s-]party payroll\b",
    re.I,
)
# Real employers whose names contain a consultancy word.
CONSULTANCY_ALLOW_RE = re.compile(r"tata consultancy|\btcs\b|accenture|deloitte|kpmg|\bey\b|pwc|mckinsey|bcg|bain", re.I)

FEE_BOND_TRAINING_RE = re.compile(
    r"registration (?:fee|charges?)|security deposit|refundable deposit|training (?:fee|cost|charges?)|course fee|"
    r"pay(?:ment)? for (?:the )?training|paid training program|unpaid training|training (?:and|&) placement|"
    r"placement (?:fee|guarantee)|\bbond\b|service agreement|\bpay to (?:join|apply)\b|"
    r"after (?:successful )?(?:completion of )?training|training period of \d|job guarantee program",
    re.I,
)

EXP_RANGE_RE = re.compile(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:yrs?|years?)\b", re.I)
EXP_PLUS_RE = re.compile(r"\b(\d{1,2})\s*\+?\s*(?:yrs?|years?)(?:\s+of)?\s+(?:experience|exp)\b", re.I)
EXP_MIN_RE = re.compile(r"\b(?:minimum|min\.?|at least)\s+(\d{1,2})\s*(?:yrs?|years?)\b", re.I)

STAGE_ORDER = ["pre-seed", "seed", "series a", "series b", "series c", "series d", "series e", "series f",
               "late stage", "growth", "ipo", "public", "acquired"]
STAGE_RE = re.compile(r"\b(pre[\s-]?seed|seed|series [a-h]|late stage|growth stage|ipo|public|acquired)\b", re.I)
SIZE_RE = re.compile(r"\b(\d{1,5})\s*(?:-|–|to)\s*(\d{1,6})\s*employees\b|\b(\d{1,6})\+\s*employees\b", re.I)


def is_consultancy(text: str, company: str | None = None) -> bool:
    blob = f"{company or ''} {text}"
    if CONSULTANCY_ALLOW_RE.search(company or ""):
        blob = text  # e.g. Tata Consultancy Services: only judge the body
        blob = CONSULTANCY_ALLOW_RE.sub("", blob)
    return bool(CONSULTANCY_RE.search(blob))


def mentions_fee_bond_training(text: str) -> bool:
    return bool(FEE_BOND_TRAINING_RE.search(text))


def min_experience_years(text: str) -> int | None:
    """Smallest 'required' years found (e.g. '2-5 Yrs' -> 2, '3+ years experience' -> 3). None if not stated."""
    values: list[int] = []
    for m in EXP_RANGE_RE.finditer(text):
        values.append(int(m.group(1)))
    for m in EXP_PLUS_RE.finditer(text):
        values.append(int(m.group(1)))
    for m in EXP_MIN_RE.finditer(text):
        values.append(int(m.group(1)))
    return min(values) if values else None


def experience_ok(text: str, max_required: int = 1) -> bool:
    lowered = text.lower()
    if "fresher" in lowered and min_experience_years(text) in (None, 0, 1):
        return True
    years = min_experience_years(text)
    return years is None or years <= max_required


def funding_stage(text: str) -> str | None:
    m = STAGE_RE.search(text)
    if not m:
        return None
    s = m.group(1).lower().replace("-", " ")
    s = "pre-seed" if s.startswith("pre") else s
    s = "growth" if s.startswith("growth") else s
    return s


def stage_ok(text: str, min_stage: str = "series a") -> bool:
    """Unknown stage is allowed (Wellfound often hides it on cards)."""
    stage = funding_stage(text)
    if stage is None or stage not in STAGE_ORDER or min_stage not in STAGE_ORDER:
        return True
    return STAGE_ORDER.index(stage) >= STAGE_ORDER.index(min_stage)


def company_size(text: str) -> tuple[int, int] | None:
    m = SIZE_RE.search(text)
    if not m:
        return None
    if m.group(3):
        n = int(m.group(3))
        return n, n * 10
    return int(m.group(1)), int(m.group(2))


def size_ok(text: str, lo: int = 11, hi: int = 500) -> bool:
    """Unknown size is allowed. Bands overlapping 11-500 pass; 1-10 and 501+ fail."""
    size = company_size(text)
    if size is None:
        return True
    a, b = size
    return b >= lo and a <= hi


SALARY_SHOW_RE = re.compile(
    r"(not disclosed|\d+(?:\.\d+)?\s*(?:-|–|to)\s*\d+(?:\.\d+)?\s*(?:lacs?|lakhs?|lpa)(?:\s*p\.?a\.?)?|"
    r"₹\s*\d+(?:\.\d+)?\s*l(?:akh)?\s*(?:-|–|to)\s*₹?\s*\d+(?:\.\d+)?\s*l(?:akh)?)",
    re.I,
)


def salary_display(text: str) -> str:
    m = SALARY_SHOW_RE.search(text or "")
    return m.group(1).strip() if m else "not listed"


def _has_term(text: str, term: str) -> bool:
    term = term.strip().lower()
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9 ]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def keyword_filter(title: str, text: str, groups: list[list[str]], title_excludes: list[str]) -> tuple[bool, str]:
    """Local boolean search, since Naukri/Wellfound ignore OR/NOT/quotes:
    (any of group 1) AND (any of group 2) ... over title+text, and NOT any exclude word in the title."""
    t = (title or "").lower()
    blob = f"{t} {(text or '').lower()}"
    for word in title_excludes:
        if _has_term(t, word):
            return False, f"title_excludes:{word.strip()}"
    for i, group in enumerate(groups, start=1):
        if group and not any(_has_term(blob, w) for w in group):
            return False, f"keywords_missing_group{i}"
    return True, "ok"


JD_END_MARKERS = (
    "beware of imposters", "fraudsters may ask", "similar jobs", "jobs you might be interested",
    "roles you might be interested", "companies hiring", "reviews by", "more jobs from", "people also viewed",
)


def jd_only(page_text: str) -> str:
    """Keep the job header + description; drop Naukri's anti-fraud footer and 'Similar jobs' sidebar,
    which mention 'registration fee' and other companies' consultancy posters."""
    lowered = page_text.lower()
    cuts = [i for i in (lowered.find(m) for m in JD_END_MARKERS) if i > 200]
    return page_text[: min(cuts)] if cuts else page_text
