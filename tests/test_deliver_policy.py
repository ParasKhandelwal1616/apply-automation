from apply_bot.apply.deliver_policy import should_auto_send_email, strip_verdict_prefix
from apply_bot.filter.legitimacy import FilterResult
from apply_bot.models import JobPost
from apply_bot.store.db import apply_status_for


def test_strip_verdict_prefix():
    assert (
        strip_verdict_prefix("[SEND] Application for SDE Intern — Paras Khandelwal")
        == "Application for SDE Intern — Paras Khandelwal"
    )
    assert strip_verdict_prefix("[REVIEW] SDE Intern - Paras") == "SDE Intern - Paras"
    assert strip_verdict_prefix("Application for SDE Intern") == "Application for SDE Intern"


def test_auto_send_only_verified_company_email():
    send = FilterResult(verdict="SEND", reason="company_domain")
    review = FilterResult(verdict="REVIEW", reason="personal_email")
    post = JobPost(company="Acme", role="SDE", source_fingerprint="a", apply_email="jobs@acme.dev")
    assert should_auto_send_email(post, send, auto_send=True) is True
    assert should_auto_send_email(post, review, auto_send=True) is False
    assert should_auto_send_email(post, send, auto_send=False) is False


def test_apply_status_maps_sent_and_submitted():
    assert apply_status_for("email_sent") == "Sent"
    assert apply_status_for("form_submitted") == "Form submitted"
    assert apply_status_for("email_sent", "Sent") == "Sent"
    assert apply_status_for("draft_created", "Sent") == "Sent"
