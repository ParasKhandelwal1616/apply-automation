from apply_bot.apply.generator import generate_draft
from apply_bot.config import Profile, load_profile
from apply_bot.filter.legitimacy import FilterResult
from apply_bot.models import JobPost


def _profile() -> Profile:
    profile = load_profile()
    if profile.full_name:
        return profile
    return Profile(full_name="Ponugupati Sumanth", batch="2026")


def test_template_uses_application_subject_and_signature(settings):
    settings.gemini_api_key = ""
    settings.grok_api_key = ""
    post = JobPost(
        company="RoadVision AI",
        role="SDE Intern",
        source_fingerprint="g",
        raw_text="Build APIs with FastAPI and React dashboards.",
        requirements=["FastAPI", "React", "AWS"],
    )
    result = FilterResult(verdict="SEND", reason="company_domain")
    draft = generate_draft(post, _profile(), result, settings)
    assert "Application for SDE Intern" in draft.subject
    assert "Hi Hiring Team," in draft.body
    assert "RoadVision AI" in draft.body
    assert "omniXM" in draft.body
    assert "GitHub: https://github.com/Sumanth3036" in draft.body
    assert "sumanthponugupati@gmail.com" in draft.body
    assert "I am writing to express my interest" not in draft.body
    assert "I believe my technical skills" not in draft.body


def test_template_follows_jd_subject_format(settings):
    settings.gemini_api_key = ""
    settings.grok_api_key = ""
    post = JobPost(
        company="Acme",
        role="SDE Intern",
        source_fingerprint="s",
        raw_text="Subject: SDE Intern - [Your Name]\nApply to jobs@acme.dev",
    )
    result = FilterResult(verdict="REVIEW", reason="personal_email")
    draft = generate_draft(post, _profile(), result, settings)
    assert "SDE Intern" in draft.subject
    assert "Ponugupati Sumanth" in draft.subject or "Sumanth Ponugupati" in draft.subject


def test_skip_cover_keeps_signature(settings):
    settings.gemini_api_key = ""
    settings.grok_api_key = ""
    post = JobPost(
        company="RoadVision AI",
        role="SDE Intern",
        source_fingerprint="c",
        raw_text="Please skip cover letter. Send resume only.",
    )
    result = FilterResult(verdict="SEND", reason="company_domain")
    draft = generate_draft(post, _profile(), result, settings)
    assert "Please find my resume" in draft.body
    assert "GitHub: https://github.com/Sumanth3036" in draft.body
