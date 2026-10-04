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
        role="Java Developer Intern",
        raw_text="Java Developer Intern Spring Boot batch 2027",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "deny_title"


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


def test_mean_stack_not_blocked_as_angular_only(settings):
    post = _post(
        role="MEAN Stack Intern",
        raw_text="MEAN Stack Intern batch 2027 Mongo Express Angular Node",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is True
