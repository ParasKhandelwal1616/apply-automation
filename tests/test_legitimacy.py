from apply_bot.filter.legitimacy import verdict_for
from apply_bot.models import JobPost


def _post(**kwargs) -> JobPost:
    data = {
        "company": "RoadVision AI",
        "role": "SDE Intern",
        "batch_includes_2027": True,
        "raw_text": "RoadVision AI SDE",
        "source_fingerprint": "x",
        "parse_source": "regex",
    }
    data.update(kwargs)
    return JobPost(**data)


def test_roadvision_company_domain_is_send(settings):
    post = _post(apply_email="hr@roadvision.ai", apply_method="email")
    result = verdict_for(post, settings)
    assert result.verdict == "SEND"


def test_microsoft_plus_gmail_is_skip(settings):
    post = _post(
        company="Microsoft",
        role="SDE Intern",
        apply_email="recruiter.ms@gmail.com",
        apply_method="email",
        raw_text="Microsoft referral apply recruiter.ms@gmail.com",
    )
    result = verdict_for(post, settings)
    assert result.verdict == "SKIP"
    assert result.reason == "brand_plus_personal_email"


def test_personal_gmail_real_company_is_review(settings):
    post = _post(
        company="Recruit CRM",
        apply_email="founder@gmail.com",
        apply_method="email",
        raw_text="Recruit CRM intern founder@gmail.com",
    )
    result = verdict_for(post, settings)
    assert result.verdict == "REVIEW"
    assert result.reason == "personal_email"


def test_nameless_form_is_skip(settings):
    post = _post(
        company=None,
        apply_url="https://forms.gle/xyz",
        apply_method="google_form",
        raw_text="Apply here https://forms.gle/xyz intern 2027",
    )
    result = verdict_for(post, settings)
    assert result.verdict == "SKIP"
    assert result.reason == "nameless_form"


def test_unrelated_email_domain_is_review(settings):
    post = _post(
        company="Glow Apps Pvt Ltd",
        apply_email="ops@rmoperation.com",
        apply_method="email",
    )
    result = verdict_for(post, settings)
    assert result.verdict == "REVIEW"
    assert result.reason == "domain_mismatch"


def test_careers_page_is_review(settings):
    post = _post(
        company="Atlan",
        apply_url="https://jobs.ashbyhq.com/atlan",
        apply_method="careers",
    )
    result = verdict_for(post, settings)
    assert result.verdict == "REVIEW"
    assert result.reason == "careers_page"


def test_low_stipend_dollar_is_review(settings):
    post = _post(
        apply_email="jobs@acme.dev",
        apply_method="email",
        stipend="$300/month",
        company="Acme",
    )
    result = verdict_for(post, settings)
    assert result.verdict == "REVIEW"
    assert result.reason == "stipend_suspicious"
