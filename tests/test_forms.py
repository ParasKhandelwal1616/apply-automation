from pathlib import Path

from apply_bot.apply.forms import (
    NEXT_BUTTON_PATTERNS,
    SUBMIT_BUTTON_PATTERNS,
    _attach_resume,
    ats_kind,
    careers_confirmed,
    is_file_upload_block,
    required_fail_reason,
    response_recorded,
    resume_shown_on_form,
)
from apply_bot.config import Profile


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


def test_file_upload_block_and_resume_chip():
    assert is_file_upload_block("Resume *\nAdd file\nFile upload\nPDF")
    assert is_file_upload_block("Upload your CV\nDrag and drop or browse")
    assert not is_file_upload_block("Full Name *\nYour answer")
    assert resume_shown_on_form("Resume\nresume.pdf\n100 KB", "resume.pdf")
    assert not resume_shown_on_form("Resume\nAdd file", "resume.pdf")


class _Loc:
    def __init__(self, page, n=0):
        self.page, self.n = page, n

    def count(self):
        return self.n

    @property
    def first(self):
        return self

    def nth(self, _):
        return self

    def set_input_files(self, path):
        self.page.uploaded = path

    def inner_text(self, timeout=0):
        return "Resume Add file" if self.n else ""


class _Page:
    def __init__(self, has_input=True, chip=True):
        self.has_input, self.chip, self.uploaded = has_input, chip, None
        self.frames = []
        self.keyboard = self

    def locator(self, sel):
        if 'type="file"' in sel:
            return _Loc(self, 1 if self.has_input else 0)
        return _Loc(self, 0)

    def inner_text(self, *_):
        name = Path(self.uploaded).name if self.uploaded else ""
        return f"Resume {name}" if (self.chip and name) else "Resume Add file"

    def wait_for_timeout(self, _):
        pass

    def press(self, _):
        pass


def test_attach_resume_sets_hidden_file_input(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF")
    page = _Page()
    profile = Profile(resume_path=str(resume))
    assert _attach_resume(page, profile) is True
    assert page.uploaded == str(resume)
