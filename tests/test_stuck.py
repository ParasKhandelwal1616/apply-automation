from apply_bot.stuck import stuck_reason
from apply_bot.filter.relevance import is_relevant
from apply_bot.models import JobPost
from apply_bot.store import db


def test_ragaai_and_customer_success_are_stuck():
    assert stuck_reason(company="RagaAI", role="Customer Success Intern") == "skip_ragaai"
    assert stuck_reason(role="Customer Success Intern") == "skip_ragaai"


def test_ats_walls_are_stuck():
    assert stuck_reason(url="https://internshala.com/internship/x") == "stuck_ats"
    assert stuck_reason(url="https://job-boards.greenhouse.io/x") == "stuck_ats"
    assert stuck_reason(company="Infobip", url="https://docs.google.com/forms/d/e/x") == "stuck_picker"


def test_customer_success_not_profile(settings):
    post = JobPost(
        company="RagaAI",
        role="Customer Success Intern",
        batch_includes_2027=True,
        raw_text="Customer Success Intern batch 2027",
        source_fingerprint="r",
    )
    ok, reason = is_relevant(post, settings, already_applied=False)
    assert ok is False
    assert reason == "not_profile"


def test_mark_stuck_skipped(tmp_path):
    conn = db.connect(tmp_path / "apps.db")
    from apply_bot.filter.legitimacy import FilterResult

    post = JobPost(
        company="RagaAI",
        role="Customer Success Intern",
        apply_url="https://docs.google.com/forms/d/e/x",
        apply_method="google_form",
        source_fingerprint="raga1",
    )
    db.record(conn, post, FilterResult(verdict="REVIEW", reason="form_needs_click"), "form_prepared")
    marked = db.mark_stuck_skipped(conn)
    assert marked
    row = conn.execute("SELECT status, reason FROM applications WHERE fingerprint='raga1'").fetchone()
    assert row["status"] == "skipped"
    assert row["reason"] == "skip_ragaai"
    assert db.incomplete_rows(conn) == []
    assert db.fingerprint_seen(conn, "raga1") is True
    conn.close()
