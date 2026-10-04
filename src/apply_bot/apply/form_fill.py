from __future__ import annotations

import re
from datetime import date, timedelta

from apply_bot.config import Profile, Settings
from apply_bot.models import ApplicationDraft, JobPost


def nearest_monday(today: date | None = None) -> date:
    today = today or date.today()
    if today.weekday() == 0:
        return today
    return today + timedelta(days=(7 - today.weekday()) % 7)

RULES: list[tuple[tuple[str, ...], str]] = (
    (("full name", "your name", "applicant name", "candidate name", "student name"), "name"),
    (("email", "e-mail", "mail id", "email address"), "email"),
    (("whatsapp", "mobile", "phone", "contact number", "contact no"), "phone"),
    (("linkedin",), "linkedin"),
    (("github",), "github"),
    (("portfolio", "personal website", "website url"), "portfolio"),
    (
        (
            "resume link",
            "link to resume",
            "cv link",
            "drive link",
            "resume url",
            "share your resume",
            "resume / cv",
            "resume/cv",
        ),
        "resume_drive",
    ),
    (("college", "university", "institute", "campus"), "college"),
    (("cgpa", "gpa"), "cgpa"),
    (
        (
            "graduation year",
            "year of graduation",
            "passing year",
            "year of passing",
            "graduating in",
            "batch",
        ),
        "batch",
    ),
    (("degree", "qualification", "course"), "degree"),
    (("branch", "specialization", "stream", "major"), "branch"),
    (("current city", "city", "current location", "hometown"), "city"),
    (("state",), "state"),
    (("country",), "country"),
    (("current company", "current organization", "present company"), "current_company"),
    (("current role", "current designation", "present role"), "current_role"),
    (("notice period", "earliest start"), "notice_period"),
    (
        (
            "experience level",
            "years of experience",
            "years of exp",
            "total experience",
            "years of professional",
            "professional engineering experience",
        ),
        "experience_years",
    ),
    (("languages known",), "languages"),
    (("applying for", "position applied", "role applied", "job role"), "role"),
    (("expected stipend", "expected ctc", "salary expectation", "stipend expectation"), "stipend"),
    (("preferred location", "preferred city"), "preferred_location"),
    (
        (
            "why should we",
            "why do you",
            "why would you",
            "cover letter",
            "about yourself",
            "tell us about",
            "motivation",
            "achievement",
        ),
        "why",
    ),
    (("relocate", "willing to relocate", "open to relocate"), "relocate"),
    (("gender",), "gender"),
    (("skills", "tech stack", "technical skills"), "skills"),
)


def _job_id_from_post(post: JobPost) -> str:
    text = f"{post.raw_text or ''} {post.apply_url or ''}"
    match = re.search(r"(?:job\s*id|jobid|req(?:uisition)?(?:\s*id)?)\s*[:#-]?\s*([A-Za-z0-9-]{4,})", text, re.I)
    return match.group(1) if match else ""


def _phone_digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("91") and len(digits) == 12:
        return digits[2:]
    return digits[-10:] if len(digits) >= 10 else digits


def fact_bank(profile: Profile, post: JobPost, draft: ApplicationDraft) -> dict[str, str]:
    proofs = " ".join(profile.proof_points[:4])
    why = (proofs or draft.body or "")[:900]
    job_stipend = re.sub(r"[^\d]", "", post.stipend or "")
    expected_stipend = (
        f"{job_stipend}/month"
        if job_stipend and job_stipend.isdigit() and 15000 <= int(job_stipend) <= 80000
        else "25000-40000/month"
    )
    current_ctc = profile.current_ctc or "3 LPA (₹25,000/month internship)"
    return {
        "name": profile.full_name,
        "email": profile.email,
        "phone": _phone_digits(profile.phone) or profile.phone,
        "linkedin": profile.linkedin,
        "github": profile.github,
        "portfolio": profile.portfolio,
        "resume_drive": profile.resume_drive,
        "college": profile.college,
        "cgpa": profile.cgpa,
        "batch": profile.graduation_year or profile.batch,
        "degree": profile.degree,
        "branch": profile.branch,
        "city": profile.city,
        "state": profile.state,
        "country": profile.country,
        "current_company": profile.current_company,
        "current_role": profile.current_role,
        "available": profile.available or "Immediate",
        "notice_period": profile.notice_period,
        "experience_years": profile.experience_years,
        "languages": profile.languages,
        "gender": profile.gender,
        "role": post.role or "",
        "company": post.company or "",
        "stipend": expected_stipend,
        "expected_stipend": expected_stipend,
        "expected_lpa": "3-6 LPA",
        "preferred_location": ", ".join(profile.preferred_locations) or profile.city,
        "skills": ", ".join(profile.skills),
        "why": why,
        "relocate": "Yes",
        "remote": "Yes",
        "join_date": nearest_monday().strftime("%d/%m/%Y"),
        "join_date_iso": nearest_monday().isoformat(),
        "duration": "6 months",
        "source": "Telegram referral / SDE Premium Group",
        "premium_group": "SDE Premium Group",
        "three_words": "Full-stack, curious, builder",
        "python_rate": "4",
        "sql_rate": "3",
        "office_yes": "Yes",
        "currently_studying": "Yes",
        "bond": "No",
        "wfh": "Yes",
        "graduated": "No",
        "blogs": "No",
        "tenth": profile.tenth,
        "twelfth": profile.twelfth,
        "leetcode": "NA",
        "job_id": _job_id_from_post(post),
        "other_stack": ", ".join(profile.skills[:4]) or "TypeScript, Python",
        "internship_exp": (
            f"Full-time: none. Internship: {profile.current_role} at "
            f"{profile.current_company} (~{profile.experience_years or '1'} year); "
            "Univ Technologies intern."
        ),
        "current_ctc": current_ctc,
        "best_project": next(
            (p for p in profile.proof_points if p),
            "",
        ),
        "two_techs": "React/Next.js and Node.js/TypeScript",
        "primary_language": "Python",
        "autonomy": "4",
        "hpc": "0",
        "complex_problem": next((p for p in profile.proof_points if p), ""),
        "failed_product": next(
            (p for p in profile.proof_points if "Runforge" in p or "88s" in p),
            next((p for p in profile.proof_points if p), ""),
        ),
    }


def _clean_q(question: str) -> str:
    text = (question or "").split("\n", 1)[0]
    return re.sub(r"[\s\xa0*：:]+", " ", text).strip().lower()


def _heading_core(question: str) -> str:
    q = _clean_q(question)
    q = re.sub(r"\s*\([^)]*\)\s*", " ", q)
    q = re.sub(r"\[[^\]]*\]", " ", q)
    return re.sub(r"\s+", " ", q).strip(" .?-")


_NOT_PERSON_NAME = (
    "college",
    "university",
    "company",
    "organization",
    "organisation",
    "institute",
    "campus",
    "father",
    "mother",
    "guardian",
    "file",
    "user name",
    "username",
    "first name",
    "last name",
    "middle name",
)


def is_person_name_question(question: str) -> bool:
    q = _heading_core(question)
    if not q or any(w in q for w in _NOT_PERSON_NAME):
        return False
    if q in {"name", "full name", "your name", "applicant name", "candidate name", "student name"}:
        return True
    return bool(re.search(r"\b(full name|your name|applicant name|candidate name|student name)\b", q))


def heading_score(question: str, heading: str) -> int:
    """Higher is better. Short headings like 'Name' must not steal college/company fills."""
    q = _heading_core(question)
    h = _heading_core(heading)
    if not q or not h:
        return 0
    if q == h:
        return 100
    shorter, longer = (q, h) if len(q) <= len(h) else (h, q)
    if shorter in {"name", "email", "city", "phone", "state"} and longer != shorter:
        if longer.startswith(shorter + " ") and len(longer) < 22:
            return 85
        return 0
    if h.startswith(q) or q.startswith(h):
        if min(len(q), len(h)) >= 8:
            return 80
        return 0
    if len(q) >= 12 and q in h:
        return 55
    if len(h) >= 12 and h in q:
        return 45
    return 0


def _phrase_in(question: str, key: str) -> bool:
    q = _heading_core(question)
    key = key.strip().lower()
    if not q or not key:
        return False
    if len(key) <= 4:
        return bool(re.search(rf"\b{re.escape(key)}\b", q))
    return key in q


KNOWN_STACK = (
    "react",
    "next.js",
    "nextjs",
    "javascript",
    "typescript",
    "node",
    "node.js",
    "python",
    "fastapi",
    "mongodb",
    "mongo",
    "redis",
    "mysql",
    "docker",
    "aws",
    "rest",
    "postgres",
    "postgresql",
    "ci/cd",
    "cicd",
    "genai",
    "gen ai",
    "express",
)

DENY_STACK = ("spring", "kubernetes", "k8s", "kotlin", "java ", "java/")


def stack_option_ticks(options: list[str]) -> list[str]:
    ticks: list[str] = []
    for opt in options:
        low = opt.strip().lower()
        if not low or any(d in low for d in DENY_STACK):
            continue
        if any(tok in low for tok in KNOWN_STACK):
            ticks.append(opt)
    return ticks


_OPTION_FRAGMENTS = {
    "yes",
    "no",
    "other",
    "other:",
    "search",
    "java",
    "kotlin",
    "both java & kotlin",
    "figma",
    "framer",
    "figjam",
}


def is_askable_question(question: str) -> bool:
    q = _clean_q(question)
    if not q or q in _OPTION_FRAGMENTS:
        return False
    if q.startswith("upload") or q.startswith("add file"):
        return False
    if "already responded" in q or "you filled out this form" in q:
        return False
    return len(q) >= 8 or "?" in q


def answer_for_question(question: str, facts: dict[str, str]) -> str:
    q = _clean_q(question)
    if q in _OPTION_FRAGMENTS:
        return ""
    if is_person_name_question(question):
        return facts.get("name") or ""
    if "first name" in q:
        return (facts.get("name") or "").split(" ")[0]
    if "last name" in q or "surname" in q:
        parts = (facts.get("name") or "").split(" ")
        return parts[-1] if len(parts) > 1 else (facts.get("name") or "")
    if any(w in q for w in ("10th", "tenth", "class 10", "class x", "12th", "twelfth", "class 12", "class xii")):
        return facts.get("tenth") if ("10" in q or "tenth" in q) else facts.get("twelfth") or ""
    if "i agree" in q or "terms" in q or "privacy" in q:
        return "Yes"
    if "relocate" in q or "willing to move" in q:
        return facts.get("relocate") or "Yes"
    if any(w in q for w in ("how soon", "immediate joiner", "when can you join")):
        return "Immediate"
    if any(w in q for w in ("available to join", "join immediately", "can you join immediately")):
        return "Yes"
    if any(w in q for w in ("authorized", "work permit")) and "india" in q:
        return "Yes"
    if "fintech" in q:
        return "No"
    if "data analytics" in q and "internship" in q:
        return "No"
    if "jee" in q:
        return "NA"
    if "job id" in q or q in {"job-id", "jobid"}:
        return facts.get("job_id") or ""
    if "graduation marks" in q or ("pre-final" in q and "mark" in q):
        return facts.get("cgpa") or ""
    if "craziest" in q or "most interesting thing you" in q:
        return facts.get("best_project") or facts.get("why") or ""
    if "job position type" in q or "position type" in q:
        return "Intern"
    if any(w in q for w in ("which role", "which job")) or ("job position" in q and "type" not in q):
        return facts.get("role") or ""
    if q in {"location"} or (q.startswith("location") and "prefer" not in q and "job" not in q):
        return facts.get("city") or ""
    if "share your resume" in q or "resume / cv" in q or "resume/cv" in q:
        return facts.get("resume_drive") or ""
    if "january 2027" in q or ("2027 onwards" in q and "intern" in q):
        return "Yes"
    if "name of the organization" in q and "intern" in q:
        return (
            f"{facts.get('current_company') or ''} (Trainee); Univ Technologies"
        ).strip()
    if "technologies have you worked" in q or ("which technologies" in q and "intern" in q):
        return facts.get("skills") or ""
    if "internship" in q and any(w in q for w in ("prior", "any prior", "completed an internship", "internship experience")):
        return "Yes"
    if any(w in q for w in ("any experience", "prior experience", "relevant experience?")) and "intern" not in q:
        return "No"
    if any(
        w in q
        for w in (
            "nearest monday",
            "joining date",
            "start date",
            "date of joining",
            "expected date of joining",
            "expected date",
            "when can you start",
            "available from",
        )
    ):
        if "iso" in q or "yyyy-mm" in q:
            return facts.get("join_date_iso") or ""
        return facts.get("join_date") or ""
    if any(w in q for w in ("internship duration", "internship period", "duration of internship")):
        return facts.get("duration") or "6 months"
    if any(
        w in q
        for w in (
            "how did you hear",
            "referred by",
            "referral source",
            "premium group",
            "premium membership",
            "telegram group",
        )
    ):
        if "premium" in q or "telegram group" in q or "name of the group" in q:
            return facts.get("premium_group") or "SDE Premium Group"
        return facts.get("source") or "Telegram referral / SDE Premium Group"
    if "three words" in q or "3 words" in q or "describe you" in q:
        return facts.get("three_words") or "Full-stack, curious, builder"
    if "rate yourself" in q or ("rate" in q and ("python" in q or "sql" in q)):
        if "python" in q:
            return facts.get("python_rate") or "4"
        if "sql" in q:
            return facts.get("sql_rate") or "3"
    if any(city in q for city in ("gurgaon", "gurugram", "pune", "noida", "bangalore", "bengaluru")):
        if any(w in q for w in ("in-office", "in office", "office", "willing", "available", "work from", "relocate", "5 day", "2 month")):
            return "Yes"
    if "currently based" in q or "where are you based" in q:
        return facts.get("city") or ""
    if any(w in q for w in ("what makes you", "good for this role", "proof of work", "why this role")):
        return facts.get("why") or facts.get("best_project") or ""
    if "job/internship title" in q or "most recent job" in q or "internship title" in q:
        return facts.get("current_role") or ""
    if "full stack app" in q or "fullstack app" in q or "complete fullstack" in q:
        return "Yes"
    if "strongest" in q and any(w in q for w in ("tech", "two", "2 ")):
        return facts.get("two_techs") or "React/Next.js and Node.js/TypeScript"
    if "ai agent" in q:
        return "Yes"
    if "most complex" in q or "complex problem" in q:
        return facts.get("complex_problem") or facts.get("best_project") or ""
    if "did not work" in q or "didn't work" in q or "product did not" in q or "customer returns" in q:
        return facts.get("failed_product") or facts.get("best_project") or ""
    if "bug you found" in q or "bug you" in q and "proud" in q:
        return facts.get("failed_product") or facts.get("best_project") or ""
    if "attracted you" in q or "choice of technology" in q:
        return facts.get("why") or facts.get("skills") or facts.get("best_project") or ""
    if "how many personal projects" in q:
        return "5+"
    if "primary language" in q or "[pe-cl]" in q or "pe-cl" in q:
        return facts.get("primary_language") or "Python"
    if "autonomy" in q:
        return facts.get("autonomy") or "4"
    if "hpc" in q:
        return facts.get("hpc") or "0"
    if "job position type" in q or "position type" in q:
        return "Intern"
    if "current ctc" in q or "current stipend" in q:
        return facts.get("current_ctc") or ""
    if any(w in q for w in ("expected stipend", "expected ctc", "salary expectation", "stipend expectation")):
        if "lpa" in q:
            return facts.get("expected_lpa") or "3-6 LPA"
        return facts.get("expected_stipend") or facts.get("stipend") or "25000-40000/month"
    if "ctc" in q and "lpa" in q:
        if "expected" in q:
            return facts.get("expected_lpa") or "3-6 LPA"
        return facts.get("current_ctc") or "3 LPA"
    if "shields" in q:
        return facts.get("why") or facts.get("best_project") or ""
    if "english" in q and "language" in q:
        return "English"
    if any(w in q for w in ("shipped to production", "which of these have you", "which internship technologies", "which tools")):
        return facts.get("skills") or ""
    if "currently studying" in q or q.startswith("graduated"):
        return "No" if "graduated" in q else "Yes"
    if "pursuing" in q:
        return "Yes"
    if "bond" in q or "service agreement" in q:
        return "No"
    if any(w in q for w in ("work from home", "wfh", "remote work", "hybrid")):
        return "Yes"
    if any(w in q for w in ("technical blog", "written any technical", "tutorials")):
        return facts.get("blogs") or "No"
    if any(w in q for w in ("leetcode", "leet code", "codechef", "codeforces", "hackerrank")):
        return facts.get("leetcode") or ""
    if "noida" in q or "willing to work from" in q:
        return "Willing to relocate"
    if "work from our" in q or "able to work from" in q:
        return "Yes"
    if any(w in q for w in ("proud of", "proud work", "work that you have done", "definitely check")):
        return facts.get("best_project") or facts.get("why") or ""
    if "programming language" in q or ("java" in q and "kotlin" in q):
        return "Other"
    if "full time" in q and "internship" in q:
        return facts.get("internship_exp") or ""
    if "current ctc" in q or "current stipend" in q:
        return facts.get("current_ctc") or ""
    if any(w in q for w in ("best project", "specific contribution", "mern stack")):
        return facts.get("best_project") or facts.get("why") or ""
    if "link to resume" in q or (q.startswith("resume") and "link" in q):
        return facts.get("resume_drive") or ""
    ranked: list[tuple[int, str]] = []
    for keys, fact_key in RULES:
        if fact_key == "name" and not is_person_name_question(question):
            continue
        hits = [key for key in keys if _phrase_in(question, key)]
        if hits and facts.get(fact_key):
            ranked.append((max(len(k) for k in hits), fact_key))
    if ranked:
        ranked.sort(reverse=True)
        return facts[ranked[0][1]]
    return ""


def map_questions_with_gemini(
    questions: list[dict],
    facts: dict[str, str],
    settings: Settings,
) -> dict[str, str]:
    if not settings.use_gemini or not questions or not settings.gemini_api_key:
        return {}
    from google import genai

    payload = [{"question": q.get("title", ""), "options": q.get("options") or []} for q in questions]
    prompt = f"""Fill an internship application form for this candidate.
Return JSON only: {{ "<exact question text>": "<answer>" }}.
If the question has options, the answer MUST be one of those option strings exactly.
Never invent skills, companies, or numbers not in the facts.
If you cannot answer honestly, use a short truthful fallback from the facts.

FACTS:
{facts}

QUESTIONS:
{payload}
"""
    try:
        from apply_bot.parse.gemini import _parse_json_object

        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
        data = _parse_json_object(getattr(response, "text", "") or "")
    except Exception as exc:
        print(f"Gemini form fill failed: {exc}")
        return {}
    return {str(k): str(v) for k, v in data.items() if v not in (None, "")}


def align_to_options(answer: str, options: list[str]) -> str:
    if not answer:
        return ""
    if not options:
        return answer
    wanted = answer.strip().lower()
    exact = next((opt for opt in options if opt.strip().lower() == wanted), None)
    if exact:
        return exact
    if wanted in {"yes", "y"}:
        hit = next((opt for opt in options if opt.strip().lower().startswith("yes")), None)
        if hit:
            return hit
    if wanted in {"no", "n"}:
        hit = next((opt for opt in options if opt.strip().lower() == "no" or opt.strip().lower().startswith("no ")), None)
        if hit:
            return hit
    if "immediate" in wanted:
        hit = next((opt for opt in options if "immediate" in opt.lower()), None)
        if hit:
            return hit
    if wanted == "other":
        hit = next((opt for opt in options if opt.strip().lower().startswith("other")), None)
        if hit:
            return hit
    contains = [opt for opt in options if wanted in opt.lower() or opt.lower() in wanted]
    if contains:
        return max(contains, key=len)
    return answer


def merge_answers(questions: list[dict], facts: dict[str, str], gemini: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for item in questions:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        gem = ""
        for key, value in gemini.items():
            if key.strip().lower() == title.lower() or title.lower() in key.lower():
                gem = value
                break
        raw = gem or answer_for_question(title, facts)
        merged[title] = align_to_options(raw, item.get("options") or [])
    return merged
