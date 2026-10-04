from __future__ import annotations

import re

from apply_bot.config import Profile, Settings
from apply_bot.models import ApplicationDraft, FilterResult, JobPost

def _closing_line(profile: Profile) -> str:
    if (profile.notes or "").strip():
        first = profile.notes.strip().split("\n")[0].strip()
        if first:
            return first
    bits = []
    if profile.degree and profile.branch:
        bits.append(f"{profile.degree} {profile.branch}")
    elif profile.degree:
        bits.append(profile.degree)
    if profile.college:
        bits.append(f"at {profile.college}")
    if profile.graduation_year or profile.batch:
        bits.append(f"({profile.graduation_year or profile.batch} batch)")
    if bits:
        return "I'm " + " ".join(bits) + "."
    return f"I'm applying for this role from the {profile.batch or 'current'} batch."

SUBJECT_FROM_JD_RE = re.compile(
    r"(?:subject\s*(?:line)?\s*[:\-]\s*)(.+)",
    re.I,
)


def _skip_cover(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in ("no cover", "skip cover", "do not write a cover", "no need for cover")
    )


def _jd_subject(raw_text: str, name: str) -> str | None:
    match = SUBJECT_FROM_JD_RE.search(raw_text or "")
    if not match:
        return None
    requested = match.group(1).strip().strip("\"'")
    requested = requested.replace("[Your Name]", name).replace("[your name]", name)
    requested = requested.replace("[Name]", name)
    if len(requested) > 120:
        return None
    return requested


def build_subject(post: JobPost, profile: Profile, result: FilterResult) -> str:
    role = (post.role or "Intern").strip()
    name = profile.full_name or "Applicant"
    requested = _jd_subject(post.raw_text or "", name)
    core = requested or f"Application for {role} — {name}"
    return f"[{result.verdict}] {core}"


def _signature(profile: Profile) -> str:
    lines = []
    if profile.resume_drive:
        lines.append(f"Resume: {profile.resume_drive}")
    if profile.portfolio:
        lines.append(f"Portfolio: {profile.portfolio}")
    if profile.github:
        lines.append(f"GitHub: {profile.github}")
    if profile.linkedin:
        lines.append(f"LinkedIn: {profile.linkedin}")
    lines.extend(
        [
            "",
            "Looking forward to the opportunity to contribute to {company}.",
            "",
            "Best regards,",
            profile.full_name,
            f"{profile.email} | {profile.phone}",
        ]
    )
    return "\n".join(lines)


def _default_bullets(profile: Profile, post: JobPost) -> list[str]:
    points = list(profile.proof_points)
    if not points:
        points = [
            f"{skill}: hands-on experience from internships and shipped projects."
            for skill in profile.skills[:3]
        ]
    reqs = [r for r in post.requirements if r][:3]
    bullets = []
    for index, point in enumerate(points[:3]):
        if index < len(reqs):
            label = reqs[index]
            if len(label) > 80:
                label = label[:77] + "..."
            bullets.append(f"{label}: {point}")
        else:
            bullets.append(point)
    return bullets


def _template_draft(post: JobPost, profile: Profile, result: FilterResult) -> ApplicationDraft:
    company = post.company or "your team"
    role = post.role or "Intern"
    subject = build_subject(post, profile, result)
    greeting = f"Hi {company} team,"
    stack = ", ".join(profile.skills[:3]) or "the skills in my profile"
    hook = (
        f"{company}'s {role} role stands out because it lines up with how I already "
        f"build and ship: {stack}."
    )
    if _skip_cover(post.raw_text or ""):
        body = (
            f"{greeting}\n\n"
            f"Please find my resume for the {role} role ({profile.batch or profile.graduation_year or 'current'} batch), as requested.\n\n"
            + _signature(profile).replace("{company}", company)
        )
    else:
        bullets = "\n\n".join(_default_bullets(profile, post))
        body = (
            f"{greeting}\n\n"
            f"{hook}\n\n"
            f"My background matches what you're looking for:\n\n"
            f"{bullets}\n\n"
            f"{_closing_line(profile)}\n\n"
            + _signature(profile).replace("{company}", company)
        )
    answers = {
        "name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "college": profile.college,
        "batch": profile.batch,
        "role": role,
        "resume": profile.resume_drive or "",
    }
    return ApplicationDraft(subject=subject, body=body, form_answers=answers)


def _gemini_prompt(post: JobPost, profile: Profile, result: FilterResult) -> str:
    return f"""Write one internship application email that follows this EXACT structure.

SUBJECT:
- Default: Application for [Exact Role Title] — {profile.full_name}
- If the JD specifies a subject format, follow THAT format exactly (replace name placeholders).
- Prefix the subject with [{result.verdict}] only (for draft sorting).

BODY (plain text, no markdown headings):
1. Hi [Team or first name if in JD],
2. Opening hook: 1-2 sentences specific to THIS company or role. Never "I am writing to express my interest."
3. Line: My background matches what you're looking for:
4. Exactly 3 bullets. Each line: [JD requirement]: [resume proof with a real number].
   Use ONLY these proof points and skills. Do not invent:
{chr(10).join('- ' + p for p in profile.proof_points) or chr(10).join('- ' + s for s in profile.skills)}
5. Closing: {_closing_line(profile)} Add location/availability only if the JD asks.
6. Signature block EXACTLY:
Resume: {profile.resume_drive}
Portfolio: {profile.portfolio}
GitHub: {profile.github}
LinkedIn: {profile.linkedin}

Looking forward to the opportunity to contribute to {post.company or 'the team'}.

Best regards,
{profile.full_name}
{profile.email} | {profile.phone}

Rules:
- Never fabricate skills or metrics.
- Startups: short and punchy. Corporates: slightly more formal.
- If JD says skip cover letter: 3-line body + the signature block only.
- Return JSON only: {{"subject": "...", "body": "...", "form_answers": {{"name": "", "email": "", "phone": "", "resume": ""}}}}

Job:
company={post.company}
role={post.role}
location={post.location}
stipend={post.stipend}
requirements={post.requirements}

JD:
{post.raw_text[:4000]}
"""


def generate_draft(
    post: JobPost,
    profile: Profile,
    result: FilterResult,
    settings: Settings,
) -> ApplicationDraft:
    fallback = _template_draft(post, profile, result)
    if not settings.use_gemini or not settings.gemini_api_key:
        return fallback

    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=_gemini_prompt(post, profile, result),
        )
        from apply_bot.parse.gemini import _parse_json_object

        data = _parse_json_object(getattr(response, "text", "") or "")
        if data.get("subject") and data.get("body"):
            answers = data.get("form_answers") or {}
            if not isinstance(answers, dict):
                answers = {}
            subject = str(data["subject"])
            if not subject.startswith(f"[{result.verdict}]"):
                subject = f"[{result.verdict}] {subject}"
            return ApplicationDraft(
                subject=subject,
                body=str(data["body"]),
                form_answers={str(k): str(v) for k, v in answers.items()} or fallback.form_answers,
            )
    except Exception:
        pass
    return fallback
