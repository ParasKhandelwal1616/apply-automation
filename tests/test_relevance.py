from apply_bot.config import Profile
from apply_bot.filter.relevance import is_relevant
from apply_bot.models import JobPost


def _post(**kwargs) -> JobPost:
    data = {
        "company": "Acme",
        "role": "SDE Intern",
        "batch_raw": "2026/2027",
        "batch_includes_2027": True,
        "raw_text": "SDE Intern batch 2026/2027 Python FastAPI",
        "source_fingerprint": "x",
        "parse_source": "regex",
    }
    data.update(kwargs)
    return JobPost(**data)


def test_stance_ai_with_fastapi_is_relevant(settings, stance_text):
    post = _post(
        company="Stance Health",
        role="AI Engineering Intern",
        raw_text=stance_text,
        apply_email="careers@stance.health",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is True
    assert reason == "ok"


def test_angular_only_skipped(settings):
    post = _post(
        role="Angular Developer Intern",
        raw_text="Role - Angular Developer Intern\nBatch - 2027",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "deny_title"


def test_batch_only_2026_skipped(settings):
    post = _post(
        batch_raw="2026",
        batch_includes_2027=False,
        raw_text="SDE Intern batch 2026",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "batch"


def test_ai_research_without_app_signals_skipped(settings):
    post = _post(
        role="AI Engineer Intern",
        raw_text="AI Engineer Intern research PyTorch papers batch 2027",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "ai_not_product"


def test_duplicate_skipped(settings):
    post = _post()
    ok, reason = is_relevant(post, settings, already_applied=True)
    assert ok is False
    assert reason == "duplicate"


def test_web_developer_not_on_old_list_is_relevant(settings):
    post = _post(
        role="Web Developer Intern",
        raw_text="Hiring Web Developer Intern batch 2026/2027 HTML CSS JS",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is True
    assert reason in {"ok", "profile_role", "profile_stack"}


def test_python_fastapi_unnamed_title_is_relevant(settings):
    post = _post(
        role="Build Intern",
        raw_text="Build Intern batch 2027. Own our Postgres and Docker services.",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is True
    assert reason == "profile_stack"


def test_marketing_intern_skipped(settings):
    post = _post(
        role="Marketing Intern",
        raw_text="Marketing Intern batch 2027. Social media and campaigns.",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "not_profile"


def test_qa_automation_skipped(settings):
    post = _post(
        role="QA Automation Intern",
        raw_text="QA Automation Intern batch 2027 Playwright Selenium",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "not_profile"


def test_flutter_only_skipped(settings):
    post = _post(
        role="Flutter Developer Intern",
        raw_text="Role - Flutter Developer Intern\nBatch - 2027",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "deny_title"


def test_spring_boot_only_skipped(settings):
    post = _post(
        role="Spring Boot Developer Intern",
        raw_text="Spring Boot Developer Intern Java Spring Boot batch 2027",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "deny_title"


def test_java_developer_title_skipped(settings):
    """Java-only titles stay out; SDE titles that merely mention Java in the JD stay in."""
    post = _post(
        role="Java Developer Intern",
        raw_text="Java Developer Intern Spring Boot batch 2027",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    # Title is not a protected SDE/Python role; no profile stack match required to skip.
    assert ok is False


def test_founding_engineer_node_is_relevant(settings):
    post = _post(
        role="Founding Engineer Intern",
        raw_text="Founding Engineer Intern 2027. Node.js and TypeScript.",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is True


def test_amts_is_relevant(settings):
    post = _post(
        role="Software Engineering - AMTS",
        raw_text="Salesforce Software Engineering AMTS batch 2026/2027",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is True


def test_cloud_devops_intern_is_relevant(settings):
    post = _post(
        role="Cloud & DevOps Engineering - Intern",
        raw_text="Cloud & DevOps Engineering Intern batch 2027 Docker AWS",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is True


def test_cybersecurity_content_skipped(settings):
    post = _post(
        role="Cybersecurity Content & Curriculum Development Intern",
        raw_text="Cybersecurity Content & Curriculum Development Intern batch 2027",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False


def test_sdet_skipped(settings):
    post = _post(
        role="SDET Intern",
        raw_text="SDET Intern batch 2027 Playwright",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False


def _fit_profile() -> Profile:
    return Profile(full_name="Sumanth", batch="2026")


def test_remote_role_that_fits_is_relevant(settings):
    post = _post(
        role="Backend Engineer",
        location="Remote",
        stipend="50000/month",
        raw_text="Backend Engineer Remote Python FastAPI stipend 50000/month batch 2026",
        batch_raw="2026",
        batch_includes_2027=False,
    )
    ok, reason = is_relevant(post, settings, already_applied=False, profile=_fit_profile())
    assert ok is True, reason


def test_pay_at_or_below_40000_skipped(settings):
    post = _post(
        role="Backend Engineer",
        location="Bengaluru",
        stipend="30000/month",
        raw_text="Backend Engineer Bengaluru Python FastAPI stipend 30000/month full time batch 2026",
        batch_raw="2026",
        batch_includes_2027=False,
    )
    ok, reason = is_relevant(post, settings, already_applied=False, profile=_fit_profile())
    assert ok is False
    assert reason == "monthly_below_min"


def test_mean_stack_not_blocked_as_angular_only(settings):
    post = _post(
        role="MEAN Stack Intern",
        raw_text="MEAN Stack Intern batch 2027 Mongo Express Angular Node",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is True


def test_software_engineer_not_denied_for_body_kotlin(settings):
    post = _post(
        role="Associate Software Engineer",
        raw_text=(
            "Associate Software Engineer batch 2025/2026/2027 Bengaluru "
            "Python FastAPI. Exposure to FastAPI, React, or Kotlin. "
            "Salary 45000/month full time"
        ),
        batch_raw="2025/2026/2027",
        location="Bengaluru",
        stipend="45000/month",
    )
    ok, reason = is_relevant(post, settings, already_applied=False, profile=_fit_profile())
    assert ok is True, reason
    assert reason != "deny_title"


def test_opportunity_word_does_not_trigger_unity_deny(settings):
    post = _post(
        role="Junior Frontend Developer",
        raw_text=(
            "Junior Frontend Developer batch 2026 Bangalore. "
            "Opportunity: join a growing startup. React TypeScript. "
            "Salary 50000/month full time"
        ),
        batch_raw="2026",
        location="Bengaluru",
        stipend="50000/month",
    )
    ok, reason = is_relevant(post, settings, already_applied=False, profile=_fit_profile())
    assert ok is True, reason


def test_taleo_net_url_does_not_deny_software_engineer(settings):
    post = _post(
        role="Software Engineer",
        raw_text=(
            "Software Engineer batch 2026 PAN India. "
            "Apply https://uhg.taleo.net/careersection/job apply. Python."
        ),
        batch_raw="2026",
        location="PAN India",
    )
    ok, reason = is_relevant(post, settings, already_applied=False, profile=_fit_profile())
    assert ok is True, reason
    assert reason != "deny_title"


def test_dotnet_title_still_denied(settings):
    post = _post(
        role="Junior .NET Full Stack Developer",
        raw_text="Junior .NET Full Stack Developer batch 2026 C# ASP.NET",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "deny_title"


def test_product_manager_still_denied(settings):
    post = _post(
        role="Product Manager",
        raw_text="Product Manager batch 2026 Bengaluru",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "deny_title"


def test_python_ai_engineer_agent_is_relevant(settings):
    post = _post(
        role="Python AI Engineer - Autonomous Agent",
        raw_text=(
            "Python AI Engineer Autonomous Agent batch 2026 Remote India "
            "Salary 50000/month. Strong Python REST APIs FastAPI LLM agents."
        ),
        batch_raw="2026",
        location="Remote",
        stipend="50000/month",
    )
    ok, reason = is_relevant(post, settings, already_applied=False, profile=_fit_profile())
    assert ok is True, reason


def test_barclays_ai_engineer_short_post_is_relevant(settings):
    post = _post(
        role="AI Engineer",
        company="Barclays",
        raw_text=(
            "Company - Barclays Role - AI Engineer Batch - 2023/2024/2025/2026 "
            "CTC - Competitive Location - PAN India"
        ),
        batch_raw="2023/2024/2025/2026",
        location="PAN India",
    )
    ok, reason = is_relevant(post, settings, already_applied=False, profile=_fit_profile())
    assert ok is True, reason


def test_sde1_frontend_gurgaon_allowed_for_fit(settings):
    post = _post(
        role="SDE 1 (Frontend)",
        company="Care.Fi",
        raw_text=(
            "Care.Fi SDE 1 Frontend batch 2024/2025/2026 Salary 50000-80000/month "
            "Location Gurgaon React TypeScript Ionic"
        ),
        batch_raw="2024/2025/2026",
        location="Gurgaon",
        stipend="50000/month",
    )
    ok, reason = is_relevant(post, settings, already_applied=False, profile=_fit_profile())
    assert ok is True, reason
