from pathlib import Path

import pytest

from apply_bot.apply import gmail_draft
from apply_bot.apply.gmail_draft import attach_resume_verified, attachment_ready, create_gmail_draft
from apply_bot.config import Profile


def test_attachment_ready_needs_chip_and_finished_upload():
    assert attachment_ready("To x Subject y resume.pdf (182K)", "resume.pdf")
    assert not attachment_ready("Uploading resume.pdf", "resume.pdf")
    assert not attachment_ready("To x Subject y", "resume.pdf")


class _Loc:
    def __init__(self, page, n=0):
        self.page, self.n = page, n

    def count(self):
        return self.n

    def filter(self, **_):
        return _Loc(self.page, 0)

    @property
    def last(self):
        return self

    @property
    def first(self):
        return self

    def set_input_files(self, path):
        self.page.uploaded = path


class _Page:
    def __init__(self, has_input=True, shows_chip=True):
        self.has_input, self.shows_chip, self.uploaded = has_input, shows_chip, None

    def locator(self, sel):
        return _Loc(self, 1 if (self.has_input and 'type="file"' in sel) else 0)

    def inner_text(self, *_):
        return f"Subject {Path(self.uploaded).name} (100K)" if (self.uploaded and self.shows_chip) else "Subject"

    def wait_for_timeout(self, _):
        pass


def test_attach_uses_file_input_and_confirms(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF")
    page = _Page()
    assert attach_resume_verified(page, resume, timeout_ms=10)
    assert page.uploaded == str(resume)


def test_attach_fails_without_input_or_chip(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF")
    assert not attach_resume_verified(_Page(has_input=False), resume, timeout_ms=10)
    assert not attach_resume_verified(_Page(shows_chip=False), resume, timeout_ms=10)


def test_project_resume_is_the_final_resume():
    root = Path(__file__).resolve().parents[1]
    final = Path("C:/Users/suman/Downloads/sumanth_ponugupati.pdf")  # updated resume, 17 Oct 2026
    if not final.exists():
        pytest.skip("source resume not on this machine")
    assert (root / "data" / "resume.pdf").read_bytes() == final.read_bytes()
