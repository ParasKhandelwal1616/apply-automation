from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from apply_bot.config import Profile, Settings
from apply_bot.llm import complete_text, llm_enabled
from apply_bot.models import ApplicationDraft, FilterResult, JobPost


class ProfileFacts:
    def __init__(self, facts_path: Path):
        with open(facts_path, "r", encoding="utf-8") as f:
            import yaml
            data = yaml.safe_load(f)

        self.proof_points = data.get("proof_points", [])
        self.intro = data.get("intro", "")
        self.locations = data.get("locations", [])
        self.banned_phrases = data.get("banned_phrases", [])

    def rank_proof_points(self, job_text: str, job_title: str, limit: int = 4) -> list[dict[str, Any]]:
        """Rank proof points by keyword match with job."""
        combined_text = f"{job_title} {job_text}".lower()

        scores = []
        for point in self.proof_points:
            tags = point.get("tags", [])
            text = point.get("text", "")
            point_id = point.get("id", "")

            score = 0
            for tag in tags:
                if tag.lower() in combined_text:
                    score += 1

            if score > 0:
                scores.append({
                    "id": point_id,
                    "text": text,
                    "tags": tags,
                    "score": score
                })

        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores[:limit]


def _llm_prompt(
    job: JobPost,
    profile: Profile,
    profile_facts: ProfileFacts,
    top_proofs: list[dict[str, Any]],
    result: FilterResult
) -> str:
    proof_text = "\n".join(
        f"{p['id']}: {p['text']}"
        for p in top_proofs
    )

    return f"""Write a job application email for this role. Return JSON only: {{"subject": "...", "body": "...", "proof_ids": ["id1", "id2"], "jd_quote": "exact phrase or null"}}.

STRICT RULES:
- Under 130 words total.
- Plain words, polite junior engineer tone.
- NO buzzwords: passionate, dynamic, cutting-edge, state-of-the-art, revolutionary, game-changer, world-class, exceptional, outstanding, unparalleled, unmatched.
- Use at most 2 proof points from the list below, the most relevant to the JD.
- Never invent facts. Use ONLY the facts provided.
- Add ONE sentence about the role or company ONLY if the JD supports it. Return the exact JD phrase used as jd_quote. If you can't find support, jd_quote is null and skip the sentence.
- Mention the resume is attached.
- End with a simple, low-pressure next step.
- Subject format: "{job.role or 'Role'} | Sumanth Ponugupati"

PROFILE FACTS (use only these):
{proof_text}

INTRO: {profile_facts.intro}
LOCATIONS: {", ".join(profile_facts.locations)}

JOB DETAILS:
Company: {job.company}
Role: {job.role}
Location: {job.location}
Stipend: {job.stipend}

JOB DESCRIPTION:
{job.raw_text[:3000]}

Return valid JSON only with subject, body, proof_ids (list of 0-2 IDs), and jd_quote (string or null)."""


def _validate_draft(
    draft_json: dict[str, Any],
    profile_facts: ProfileFacts,
    job: JobPost,
    max_words: int = 150
) -> tuple[bool, list[str]]:
    """Validate the LLM-generated draft."""
    problems = []

    # Check structure
    if not draft_json.get("subject"):
        problems.append("Missing subject")
    if not draft_json.get("body"):
        problems.append("Missing body")

    # Check word count
    body = draft_json.get("body", "")
    word_count = len(body.split())
    if word_count > max_words:
        problems.append(f"Too many words: {word_count} (max {max_words})")

    # Check for banned phrases
    for phrase in profile_facts.banned_phrases:
        if phrase.lower() in body.lower():
            problems.append(f"Banned phrase: '{phrase}'")

    # Check proof_ids
    proof_ids = draft_json.get("proof_ids", [])
    valid_ids = {p["id"] for p in profile_facts.proof_points}
    if len(proof_ids) > 2:
        problems.append(f"Too many proof_ids: {len(proof_ids)} (max 2)")
    for pid in proof_ids:
        if pid not in valid_ids:
            problems.append(f"Invalid proof_id: {pid}")

    # Check jd_quote is verbatim from JD
    jd_quote = draft_json.get("jd_quote")
    if jd_quote and jd_quote != "null":
        if jd_quote not in job.raw_text:
            problems.append(f"jd_quote not in JD: '{jd_quote}'")

    # Check for invented numbers
    all_numbers = re.findall(r'\d+\.?\d*', body)
    proof_numbers = re.findall(r'\d+\.?\d*', "\n".join(p["text"] for p in profile_facts.proof_points))
    jd_numbers = re.findall(r'\d+\.?\d*', job.raw_text)

    for num in all_numbers:
        if num not in proof_numbers and num not in jd_numbers:
            problems.append(f"Invented number: {num}")

    return len(problems) == 0, problems


def _hr_subject(profile: Profile, job: JobPost) -> str:
    role = (job.role or "Role").strip()
    name = profile.full_name or "Sumanth Ponugupati"
    return f"Application for {role} | {name}"


def _hr_signature(profile: Profile) -> str:
    return (
        f"Best regards,\n"
        f"{profile.full_name}\n"
        f"{profile.phone}\n"
        f"Email: {profile.email}\n"
        f"LinkedIn: {profile.linkedin}\n"
        f"GitHub: {profile.github}"
    )


def _form_answers(profile: Profile) -> dict[str, str]:
    return {
        "name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "resume": profile.resume_drive or "",
    }


def _build_hr_email(profile: Profile, job: JobPost) -> ApplicationDraft:
    role = job.role or "open role"
    company = job.company or "your company"
    body = f"""Hi Hiring Team,

I am writing to apply for the {role} position at {company}.

I hold a B.Tech degree in Electronics and Computer Engineering and have industry and research experience in software development, AI/ML, backend engineering, and building end-to-end technical solutions.

Currently, I am working as a Trainee Engineer at omniXM, where I contribute to production systems, application development, and performance optimisation. I have also gained research experience at IIT Kharagpur and industry experience at LogiXair.

Please find my resume attached for your review. I would appreciate the opportunity to discuss my application further.

Thank you for your time and consideration.

{_hr_signature(profile)}"""
    return ApplicationDraft(subject=_hr_subject(profile, job), body=body, form_answers=_form_answers(profile))


def _build_fallback_email(
    profile: Profile,
    profile_facts: ProfileFacts,
    top_proofs: list[dict[str, Any]],
    job: JobPost
) -> ApplicationDraft:
    return _build_hr_email(profile, job)


def _build_minimal_email(
    profile: Profile,
    job: JobPost
) -> ApplicationDraft:
    role = job.role or "open role"
    company = job.company or "your company"
    body = f"""Hi Hiring Team,

I am writing to apply for the {role} position at {company}.

Please find my resume attached for your review.

Thank you for your time and consideration.

{_hr_signature(profile)}"""
    return ApplicationDraft(subject=_hr_subject(profile, job), body=body, form_answers=_form_answers(profile))


def generate_llm_email(
    job: JobPost,
    profile: Profile,
    result: FilterResult,
    settings: Settings,
    dry_run: bool = False
) -> tuple[ApplicationDraft, str, list[str]]:
    """Build the HR application email. Role and company are filled from the post."""
    if "skip cover" in job.raw_text.lower() or "no cover letter" in job.raw_text.lower():
        return _build_minimal_email(profile, job), "minimal", []
    return _build_hr_email(profile, job), "hr_template", []
