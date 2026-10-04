from apply_bot.apply.generator import generate_draft
from apply_bot.config import Profile, load_profile
from apply_bot.filter.legitimacy import FilterResult
from apply_bot.models import JobPost


def _profile() -> Profile:
    profile = load_profile()
    if profile.full_name:
        return profile
    return Profile(full_name="Paras Khandelwal", batch="2027")


def test_template_uses_application_subject_and_signature(settings):
    settings.gemini_api_key = ""
    post = JobPost(
        company="RoadVision AI",
        role="SDE Intern",
        source_fingerprint="g",
        raw_text="Build APIs with FastAPI and React dashboards.",
        requirements=["FastAPI", "React", "AWS"],
    )
    result = FilterResult(verdict="SEND", reason="company_domain")
    draft = generate_draft(post, _profile(), result, settings)
    assert draft.subject.startswith("[SEND] Application for SDE Intern — Paras Khandelwal")
    assert "My background matches what you're looking for:" in draft.body
    assert "Resume: https://drive.google.com/file/d/" in draft.body
    assert "Portfolio: https://paras-portfolio-eight.vercel.app" in draft.body
    assert "GitHub: https://github.com/ParasKhandelwal1616" in draft.body
    assert "LinkedIn: https://linkedin.com/in/paras-khandelwal" in draft.body
    assert "MITS Gwalior" in draft.body
    assert "parasprince161616@gmail.com" in draft.body
    assert "I am writing to express my interest" not in draft.body


def test_template_follows_jd_subject_format(settings):
    settings.gemini_api_key = ""
    post = JobPost(
        company="Acme",
        role="SDE Intern",
        source_fingerprint="s",
        raw_text="Subject: SDE Intern - [Your Name]\nApply to jobs@acme.dev",
    )
    result = FilterResult(verdict="REVIEW", reason="personal_email")
    draft = generate_draft(post, _profile(), result, settings)
    assert draft.subject == "[REVIEW] SDE Intern - Paras Khandelwal"


def test_skip_cover_keeps_signature(settings):
    settings.gemini_api_key = ""
    post = JobPost(
        company="RoadVision AI",
        role="SDE Intern",
        source_fingerprint="c",
        raw_text="Please skip cover letter. Send resume only.",
    )
    result = FilterResult(verdict="SEND", reason="company_domain")
    draft = generate_draft(post, _profile(), result, settings)
    assert "Please find my resume" in draft.body
    assert "Resume: https://drive.google.com/file/d/" in draft.body
