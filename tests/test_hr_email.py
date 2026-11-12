from apply_bot.apply.llm_email import generate_llm_email
from apply_bot.config import Profile
from apply_bot.models import FilterResult, JobPost


def _profile() -> Profile:
    return Profile(
        full_name="Sumanth Ponugupati",
        email="sumanthponugupati@gmail.com",
        phone="+91 9110368779",
        linkedin="https://linkedin.com/in/sumanthponugupati",
        github="https://github.com/Sumanth3036",
        batch="2026",
    )


def test_hr_template_fills_role_and_company(settings):
    settings.gemini_api_key = ""
    settings.grok_api_key = ""
    post = JobPost(
        company="Acme Labs",
        role="Backend Engineer",
        source_fingerprint="hr1",
        raw_text="We need a backend engineer in Bengaluru.",
    )
    draft, source, problems = generate_llm_email(
        post, _profile(), FilterResult(verdict="SEND", reason="company_domain"), settings
    )
    assert source == "hr_template"
    assert problems == []
    assert draft.subject == "Application for Backend Engineer | Sumanth Ponugupati"
    assert draft.body.startswith("Hi Hiring Team,")
    assert "apply for the Backend Engineer position at Acme Labs" in draft.body
    assert "B.Tech degree in Electronics and Computer Engineering" in draft.body
    assert "Trainee Engineer at omniXM" in draft.body
    assert "IIT Kharagpur" in draft.body
    assert "LogiXair" in draft.body
    assert "I believe my technical skills" not in draft.body
    assert "Please find my resume attached" in draft.body
    assert "Email: sumanthponugupati@gmail.com" in draft.body
    assert "+91 9110368779" in draft.body
    assert "LinkedIn: https://linkedin.com/in/sumanthponugupati" in draft.body
    assert "GitHub: https://github.com/Sumanth3036" in draft.body


def test_skip_cover_is_short_hr_mail(settings):
    settings.gemini_api_key = ""
    settings.grok_api_key = ""
    post = JobPost(
        company="Acme Labs",
        role="SDE",
        source_fingerprint="hr2",
        raw_text="Please skip cover letter. Send resume only.",
    )
    draft, source, _ = generate_llm_email(
        post, _profile(), FilterResult(verdict="SEND", reason="ok"), settings
    )
    assert source == "minimal"
    assert "Please find my resume attached" in draft.body
    assert "Trainee Engineer at omniXM" not in draft.body
    assert "Email: sumanthponugupati@gmail.com" in draft.body
