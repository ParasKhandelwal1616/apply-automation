from apply_bot.parse.regex import batch_includes_2027, parse_job_regex


def test_roadvision_regex(roadvision_text):
    post = parse_job_regex(roadvision_text, source_fingerprint="rv")
    assert post.company == "RoadVision AI"
    assert "Software Development Engineer Intern" in (post.role or "")
    assert post.batch_includes_2027 is True
    assert post.apply_email == "hr@roadvision.ai"
    assert post.apply_url and "forms.gle" in post.apply_url
    assert post.apply_method == "email_and_form"
    assert post.location == "New Delhi"
    assert post.parse_source == "regex"


def test_stance_regex(stance_text):
    post = parse_job_regex(stance_text, source_fingerprint="st")
    assert post.company == "Stance Health"
    assert post.role == "AI Engineering Intern"
    assert post.batch_includes_2027 is True
    assert post.apply_email == "careers@stance.health"
    assert post.apply_url is None
    assert post.apply_method == "email"
    assert post.location == "Bengaluru"


def test_form_only_post():
    text = """
Company - NoMail Labs
Role - Full Stack Developer Intern
Batch - 2027
How to Apply:
https://docs.google.com/forms/d/e/abc123/viewform
"""
    post = parse_job_regex(text, source_fingerprint="form")
    assert post.apply_method == "google_form"
    assert post.apply_email is None
    assert post.apply_url and "docs.google.com/forms" in post.apply_url


def test_email_only_post():
    text = """
Company - Acme
Role - Backend Developer Intern
Batch - 2026/2027
How to Apply: send CV to jobs@acme.dev
"""
    post = parse_job_regex(text, source_fingerprint="mail")
    assert post.apply_method == "email"
    assert post.apply_email == "jobs@acme.dev"
    assert post.apply_url is None


def test_batch_includes_2027_variants():
    assert batch_includes_2027("Batch - 2025/2026/2027")
    assert batch_includes_2027("2026/27")
    assert batch_includes_2027("2026-27")
    assert batch_includes_2027("batch 2027")
    assert not batch_includes_2027("Batch - 2025/2026")
    assert not batch_includes_2027("")
