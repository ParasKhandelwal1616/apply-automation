from apply_bot.apply.forms import (
    NEXT_BUTTON_PATTERNS,
    SUBMIT_BUTTON_PATTERNS,
    ats_kind,
    careers_confirmed,
    required_fail_reason,
    response_recorded,
)


def test_response_recorded_google_success():
    assert response_recorded("Thanks. Your response has been recorded.") is True
    assert response_recorded("Response has been recorded") is True
    assert response_recorded("You've already responded") is True


def test_response_recorded_not_yet():
    assert response_recorded("Internship application — Submit") is False
    assert response_recorded("") is False


def test_submit_patterns_include_send_and_submit():
    joined = " ".join(SUBMIT_BUTTON_PATTERNS)
    assert "Submit" in joined or "submit" in joined.lower()
    assert "Send" in joined or "send" in joined.lower()


def test_next_patterns_include_continue():
    joined = " ".join(NEXT_BUTTON_PATTERNS).lower()
    assert "next" in joined
    assert "continue" in joined


def test_required_fail_reason_from_google_error():
    body = "Name\nThis is a required question\nResume\nThis is a required question"
    reason = required_fail_reason(body, ["Name", "College", "Resume"])
    assert reason.startswith("missing:")
    assert "Resume" in reason or "Name" in reason


def test_required_fail_reason_generic():
    assert required_fail_reason("almost done", []) == "submit_not_confirmed"


def test_closed_google_form_reason():
    assert required_fail_reason(
        "The form Bright Money is no longer accepting responses."
    ) == "form_closed"


def test_careers_click_without_thanks_is_not_confirmed():
    assert careers_confirmed("Apply now to join our team") is False


def test_careers_thank_you_is_confirmed():
    assert careers_confirmed("Thank you. Your application has been received.") is True
    assert careers_confirmed("Application submitted successfully") is True


def test_ats_kind_from_url():
    assert ats_kind("https://ats.rippling.com/en-GB/sanas/jobs/x/apply") == "rippling"
    assert ats_kind("https://nextracker.wd5.myworkdayjobs.com/en-US/job") == "workday"
    assert ats_kind("https://internshala.com/internship/detail/x") == "internshala"
    assert ats_kind("https://wellfound.com/jobs/1") == "wellfound"
    assert ats_kind("https://docs.google.com/forms/d/e/x") == "google_form"
