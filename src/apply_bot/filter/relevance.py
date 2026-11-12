from __future__ import annotations

import re

from apply_bot.config import Profile, Settings
from apply_bot.models import JobPost
from apply_bot.llm import complete_text, llm_enabled
from apply_bot.parse.gemini import _parse_json_object
from apply_bot.boards.rules import experience_ok

REACT_OR_ANGULAR_RE = re.compile(
    r"react\s*(?:or|/|,|\\|and)\s*angular|angular\s*(?:or|/|,|\\|and)\s*react",
    re.I,
)
AI_ENGINEER_RE = re.compile(r"\bai\s+engineer", re.I)
MEAN_RE = re.compile(r"\bmean\b", re.I)

SOFTWARE_ROLE_RE = re.compile(
    r"(?:"
    r"intern|trainee|"
    r"\bsde\b|\bswe\b|"
    r"software|developer|programmer|"
    r"full[\s-]?stack|backend|frontend|fullstack|"
    r"web developer|application developer|app developer|"
    r"product engineer|founding engineer|"
    r"member of technical|\bmts\b|"
    r"graduate engineer|junior (?:software|developer|engineer)|"
    r"associate (?:software|engineer|developer)|"
    r"tech(?:nical)? intern|engineering intern|"
    r"devops|cloud engineer|platform engineer|"
    r"genai|gen ai|llm|rag"
    r")",
    re.I,
)

GENERIC_SOFTWARE_RE = re.compile(
    r"(?:"
    r"software (?:development )?engineer|"
    r"software developer|software intern|"
    r"\bsde\b|\bswe\b|"
    r"developer intern|engineering intern|"
    r"tech(?:nical)? intern|product engineer|"
    r"founding engineer|web developer|web intern|"
    r"application developer|app developer|"
    r"junior software|associate software|"
    r"graduate engineer trainee|\bget\b|"
    r"member of technical staff|\bmts\b|"
    r"full[\s-]?stack|frontend intern|backend intern|"
    r"devops intern|cloud intern|cloud & devops|cloud and devops|"
    r"\bamts\b|associate member of technical"
    r")",
    re.I,
)

NON_TECH_RE = re.compile(
    r"(?:"
    r"marketing intern|digital marketing|sales intern|"
    r"hr intern|human resources|recruiter|"
    r"campus ambassador|content writer|copywriter|"
    r"graphic design|ui/?ux designer|ux designer|ui designer|"
    r"business development|\bbde\b|bd intern|"
    r"chartered account|\bca intern\b|accountant|"
    r"mechanical intern|civil intern|electrical intern|"
    r"vlsi|\bfpga\b|hardware intern|"
    r"influencer|social media intern|seo intern|"
    r"qa intern|qa trainee|qa automation|quality analyst|"
    r"manual tester|test automation intern|sdet|"
    r"cybersecurity content|curriculum development|"
    r"content & curriculum|content and curriculum|"
    r"customer success"
    r")",
    re.I,
)

DEFAULT_STACK = (
    "react",
    "next.js",
    "nextjs",
    "node",
    "nodejs",
    "node.js",
    "express",
    "typescript",
    "javascript",
    "python",
    "fastapi",
    "mongodb",
    "mongo",
    "redis",
    "mysql",
    "docker",
    "aws",
    "nginx",
    "gemini",
    "groq",
    "rag",
    "llm",
    "genai",
    "gen ai",
    "ci/cd",
    "cicd",
    "mern",
    "rest api",
    "postgres",
    "postgresql",
    "tailwind",
)


def _haystack(post: JobPost) -> str:
    reqs = " ".join(post.requirements or [])
    return f"{post.role or ''} {post.raw_text} {reqs}".lower()


def _contains_any(text: str, needles: list[str]) -> str | None:
    """Substring search (legacy). Prefer _deny_hit for deny_titles."""
    for needle in needles:
        if needle and needle.lower() in text:
            return needle
    return None


# Tech-stack denies must match the ROLE TITLE only. Matching the full JD/body
# caused mass false skips: "unity" inside "Opportunity", ".net" inside taleo.net /
# avature.net URLs, and nice-to-have Kotlin/.NET tracks on Software Engineer posts.
_TITLE_SCOPED_DENY = {
    ".net",
    "dotnet",
    "swift",
    "kotlin",
    "android native",
    "ios native",
    "embedded",
    "manual qa",
    "testing-only",
    "sre",
    "site reliability",
    "php intern",
    "laravel",
    "wordpress",
    "core java",
    "java intern",
    "java developer",
    "salesforce admin",
    "salesforce developer",
    "unity",
    "unreal engine",
    "vlsi",
    "firmware",
    "angular",
    "flutter",
    "spring boot",
    "spring",
}

# Role titles that are clearly SDE/AI and must never die on a body tech keyword.
_PROTECTED_ROLE_RE = re.compile(
    r"(?:"
    r"\bsde\b|\bswe\b|"
    r"software (?:development )?engineer|software developer|"
    r"associate software|junior software|"
    r"full[\s-]?stack|backend|frontend|"
    r"python (?:ai |ml )?engineer|ai engineer|ml engineer|"
    r"machine learning engineer|data engineer|data analyst|"
    r"devops engineer|cloud engineer|platform engineer|"
    r"genai|llm engineer|rag engineer"
    r")",
    re.I,
)


def _has_term(text: str, term: str) -> bool:
    term = (term or "").strip().lower()
    if not term:
        return False
    # Dotted tokens like ".net" must not match hostnames (taleo.net, avature.net).
    if term.startswith("."):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    if re.fullmatch(r"[a-z0-9 .+#]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def _deny_hit(role: str, text: str, deny_titles: list[str]) -> str | None:
    """Return the deny needle that should block this post, or None.

    - Tech-stack denies (.net, kotlin, unity, …): title only, word-boundary.
    - Soft/non-tech denies (product manager, service desk, maximo): title first,
      then body with word-boundary (so Opportunity≠unity never fires here).
    - Protected SDE/AI titles ignore title-scoped tech denies entirely when the
      deny token is absent from the title.
    """
    role_l = (role or "").lower()
    body_l = (text or "").lower()
    protected = bool(_PROTECTED_ROLE_RE.search(role_l))

    for needle in deny_titles:
        raw = (needle or "").strip()
        if not raw:
            continue
        key = raw.lower()
        title_scoped = key in _TITLE_SCOPED_DENY or key.lstrip(".") in {
            x.lstrip(".") for x in _TITLE_SCOPED_DENY
        }

        if title_scoped:
            if protected and not _has_term(role_l, key):
                continue
            if _has_term(role_l, key) and not _deny_is_exception(key, role_l):
                return raw
            continue

        # Managerial / non-tech: prefer title, allow body match with boundaries.
        if _has_term(role_l, key) or _has_term(body_l, key):
            if not _deny_is_exception(key, f"{role_l} {body_l}"):
                return raw
    return None


def _stack_needles(settings: Settings, profile: Profile | None) -> list[str]:
    needles = list(settings.profile_stack_signals or DEFAULT_STACK)
    if profile:
        for skill in profile.skills:
            for token in re.findall(r"[a-z0-9.+#]+", skill.lower()):
                if len(token) >= 3 and token not in {"and", "the", "with", "for"}:
                    needles.append(token)
    seen: set[str] = set()
    unique: list[str] = []
    for item in needles:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _deny_is_exception(deny_hit: str, text: str) -> bool:
    if deny_hit != "angular":
        return False
    return bool(REACT_OR_ANGULAR_RE.search(text) or MEAN_RE.search(text))


def _batch_matches(post: JobPost, profile: Profile | None) -> bool:
    if profile is None:
        return post.batch_includes_2027
    target_batch = str(profile.batch or "2026").strip()
    haystack = f"{post.batch_raw or ''} {post.raw_text or ''}".lower()
    batch_kw = re.search(r"\bbatch\b|\bgraduation\b|\bpassing\s+out\b", haystack)
    if not batch_kw and ("full time" in haystack or "full-time" in haystack or "sde" in haystack):
        return True
    if target_batch in haystack:
        return True
    if target_batch == "2026" and re.search(r"2026|20?25\s*[/\-–]\s*20?26|20?26\s*[/\-–]\s*20?27", haystack):
        return True
    if post.batch_includes_2027 and target_batch == "2027":
        return True
    if not post.batch_raw and not batch_kw:
        return True
    return False


def _gemini_profile_fit(
    post: JobPost,
    settings: Settings,
    profile: Profile | None,
) -> bool | None:
    if not llm_enabled(settings):
        return None
    skills = ", ".join(profile.skills) if profile and profile.skills else ", ".join(DEFAULT_STACK[:12])
    batch_desc = f"{profile.batch} graduate" if profile and profile.batch else "2026/2027 graduate"
    prompt = (
        "Decide if this candidate should apply. Return ONLY JSON "
        '{"apply": true/false, "reason": "short"}.\n\n'
        f"CANDIDATE: {batch_desc}. Stack: {skills}. "
        f"Target: Full-time software roles (SDE, Backend, Python, ML/AI, FastAPI) with CTC >= {settings.min_ctc_lpa} LPA. "
        "YES for software engineer/dev, fullstack, frontend, backend, "
        f"GenAI product, AI/ML engineer, or adjacent roles they can do with CTC >= {settings.min_ctc_lpa} LPA. "
        f"Roles asking up to {settings.telegram_max_experience_years} years of experience are OK (e.g. 0-2, 1-4, 2+ years); "
        f"NO if the minimum required experience is above {settings.telegram_max_experience_years} years or the batch excludes {profile.batch if profile else '2026'} graduates. "
        f"NO for internships, roles below {settings.min_ctc_lpa} LPA, Angular-only, .NET, native iOS/Android, Flutter, PHP, "
        "Java/Spring-only, embedded/hardware, SRE, manual QA, ML research, "
        "marketing/sales/HR/design-only.\n\n"
        f"ROLE: {post.role or ''}\n"
        f"POST:\n{(post.raw_text or '')[:3500]}"
    )
    done = complete_text(settings, prompt)
    if not done:
        return None
    data = _parse_json_object(done[1])
    if not data or "apply" not in data:
        return None
    return bool(data["apply"])


def is_relevant(
    post: JobPost,
    settings: Settings,
    already_applied: bool,
    profile: Profile | None = None,
) -> tuple[bool, str]:
    if already_applied:
        return False, "duplicate"

    if profile is None:
        if not post.batch_includes_2027:
            return False, "batch"
    else:
        if not _batch_matches(post, profile):
            return False, "batch"

    text = _haystack(post)
    if not experience_ok(text, settings.telegram_max_experience_years):
        return False, f"experience_gt_{settings.telegram_max_experience_years}y"
    if NON_TECH_RE.search(text):
        return False, "not_profile"

    deny_hit = _deny_hit(post.role or "", text, settings.deny_titles)
    if deny_hit:
        return False, "deny_title"

    # Full-time, salary, and location filter for candidates seeking full-time roles in targeted cities
    if profile is not None:
        from apply_bot.boards.fit import location_ok, salary_ok
        pay_text = f"{text} {post.stipend or ''} {post.location or ''}"
        ok_sal, why_sal = salary_ok(pay_text, settings, usd=True)
        if not ok_sal:
            return False, why_sal
        # Full-time preferred; good interns OK (PPO / strong stipend / named company).
        # Do not hard-skip intern titles when pay/location otherwise fit.
        loc_text = f"{text} {post.location or ''}"
        has_location_indicator = bool(post.location) or any(
            kw in loc_text for kw in ["location", "city", "office", "onsite", "hybrid", "remote", "noida", "delhi", "gurugram", "gurgaon", "pune", "mumbai", "kolkata", "wfh", "pan india", "pan-india"]
        )
        if has_location_indicator and not location_ok(loc_text, settings, allow_remote_india=True):
            # Prefer BLR/HYD/CHN; still allow strong / pan-India / metro posts.
            strong = bool(
                re.search(
                    r"\b(?:barclays|google|microsoft|amazon|meta|flipkart|amazon|nvidia|oracle|adobe|uber|databricks|visa|goldman|morgan stanley|jp ?morgan|deutsche|citi|hsbc)\b",
                    loc_text,
                    re.I,
                )
            )
            pan = bool(re.search(r"pan[\s-]?india|anywhere in india|multiple locations|across india", loc_text, re.I))
            if not (strong or pan):
                return False, "location"

    is_ai_engineer = bool(AI_ENGINEER_RE.search(text))
    if is_ai_engineer:
        if _contains_any(text, settings.ai_engineer_app_signals):
            return True, "ok"
        # Short referral posts (e.g. Barclays AI Engineer) often omit stack keywords.
        # Only hard-skip clear research-track AI roles without product/app signals.
        if re.search(r"\b(?:research|papers?|phd|publication)\b", text, re.I):
            return False, "ai_not_product"
        return True, "ok"

    if _contains_any(text, settings.allow_titles):
        return True, "ok"

    if SOFTWARE_ROLE_RE.search(text) and _contains_any(text, _stack_needles(settings, profile)):
        return True, "profile_stack"

    if GENERIC_SOFTWARE_RE.search(text):
        return True, "profile_role"

    if SOFTWARE_ROLE_RE.search(text) and llm_enabled(settings):
        gemini = _gemini_profile_fit(post, settings, profile)
        if gemini is True:
            return True, "profile_gemini"
        if gemini is False:
            return False, "not_profile"

    return False, "no_title_match"
