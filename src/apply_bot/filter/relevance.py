from __future__ import annotations

import re

from apply_bot.config import Profile, Settings
from apply_bot.models import JobPost
from apply_bot.parse.gemini import _client, _parse_json_object

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
    for needle in needles:
        if needle and needle.lower() in text:
            return needle
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


def _gemini_profile_fit(
    post: JobPost,
    settings: Settings,
    profile: Profile | None,
) -> bool | None:
    client = _client(settings)
    if client is None:
        return None
    skills = ", ".join(profile.skills) if profile and profile.skills else ", ".join(DEFAULT_STACK[:12])
    prompt = (
        "Decide if this candidate should apply. Return ONLY JSON "
        '{"apply": true/false, "reason": "short"}.\n\n'
        "CANDIDATE: 2027 CSE intern. Stack: "
        f"{skills}. "
        "YES for software intern/dev/engineer, fullstack, frontend, backend, "
        "web, GenAI product, DevOps intern, or adjacent roles they can do. "
        "YES if the title is unusual but the work is software they can build. "
        "NO for Angular-only, .NET, native iOS/Android, Flutter, PHP, "
        "Java/Spring-only, embedded/hardware, SRE, manual QA, ML research, "
        "marketing/sales/HR/design-only.\n\n"
        f"ROLE: {post.role or ''}\n"
        f"POST:\n{(post.raw_text or '')[:3500]}"
    )
    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
    except Exception as exc:
        print(f"Gemini fit check failed: {exc}")
        return None
    data = _parse_json_object(getattr(response, "text", "") or "")
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
    if not post.batch_includes_2027:
        return False, "batch"

    text = _haystack(post)
    if NON_TECH_RE.search(text):
        return False, "not_profile"

    deny_hit = _contains_any(text, settings.deny_titles)
    if deny_hit and not _deny_is_exception(deny_hit, text):
        return False, "deny_title"

    is_ai_engineer = bool(AI_ENGINEER_RE.search(text))
    if is_ai_engineer:
        if _contains_any(text, settings.ai_engineer_app_signals):
            return True, "ok"
        return False, "ai_not_product"

    if _contains_any(text, settings.allow_titles):
        return True, "ok"

    if SOFTWARE_ROLE_RE.search(text) and _contains_any(text, _stack_needles(settings, profile)):
        return True, "profile_stack"

    if GENERIC_SOFTWARE_RE.search(text):
        return True, "profile_role"

    if SOFTWARE_ROLE_RE.search(text) and settings.use_gemini and settings.gemini_api_key:
        gemini = _gemini_profile_fit(post, settings, profile)
        if gemini is True:
            return True, "profile_gemini"
        if gemini is False:
            return False, "not_profile"

    return False, "no_title_match"
