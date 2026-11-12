from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page

from apply_bot.apply.deliver_policy import strip_verdict_prefix
from apply_bot.config import Profile
from apply_bot.models import ApplicationDraft, JobPost


def create_gmail_draft(
    page: Page,
    post: JobPost,
    draft: ApplicationDraft,
    profile: Profile,
    send: bool = False,
) -> bool:
    to_addr = post.apply_email
    if not to_addr:
        raise RuntimeError("No apply email for Gmail draft")

    page.goto("https://mail.google.com/mail/u/0/#inbox", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    deadline = time.time() + 180
    while time.time() < deadline:
        body_text = (page.inner_text("body") or "").lower()
        signed_out = "sign in" in body_text and "compose" not in body_text
        if not signed_out:
            break
        print("Sign into Gmail in this Chromium window. Waiting up to 3 minutes...")
        page.wait_for_timeout(5000)
    else:
        raise RuntimeError("Log into Gmail in this browser profile once, then rerun.")

    for _ in range(2):
        try:
            discard = page.locator('[aria-label="Discard draft"], [data-tooltip="Discard draft"]')
            if discard.count() and discard.first.is_visible(timeout=400):
                discard.first.click()
                page.wait_for_timeout(400)
        except Exception:
            break

    try:
        page.locator('div[role="button"][gh="cm"]').first.click(timeout=6000)
    except Exception:
        page.goto("https://mail.google.com/mail/u/0/#inbox?compose=new", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    for selector in (
        "div.aoD.hl",
        'input[aria-label="To recipients"]',
        'textarea[name="to"]',
        'div[aria-label="To"]',
    ):
        loc = page.locator(selector)
        try:
            if loc.count():
                loc.first.click(timeout=1500, force=True)
                page.wait_for_timeout(250)
                break
        except Exception:
            continue

    to_box = page.locator(
        'input[aria-label="To recipients"], input[aria-label="To"], textarea[name="to"]'
    )
    filled = False
    try:
        count = to_box.count()
    except Exception:
        count = 0
    for i in range(count):
        el = to_box.nth(i)
        try:
            if el.is_visible(timeout=900):
                el.fill(to_addr)
                filled = True
                break
        except Exception:
            continue
    if not filled:
        to_box.first.fill(to_addr, force=True)
    try:
        page.keyboard.press("Tab")
    except Exception:
        pass

    subject_text = strip_verdict_prefix(draft.subject) if send else draft.subject
    subject = page.locator('input[name="subjectbox"]').first
    subject.fill(subject_text)

    body = page.locator('div[aria-label="Message Body"], div[role="textbox"]').first
    body.click()
    body.fill(draft.body)

    resume = Path(profile.resume_path).expanduser() if profile.resume_path else None
    if not resume or not resume.exists():
        raise RuntimeError(f"resume_missing: {profile.resume_path}")
    if not attach_resume_verified(page, resume):
        raise RuntimeError("resume_not_attached: Gmail did not show the attachment; not sending")
    print(f"    resume attached: {resume.name}")

    page.wait_for_timeout(1000)
    if not send:
        page.keyboard.press("Control+s")
        page.wait_for_timeout(1500)
        return False

    send_btn = page.locator(
        'div[role="button"][aria-label*="Send"], div[role="button"][data-tooltip*="Send"]'
    ).first
    try:
        send_btn.click(timeout=8000)
    except Exception:
        page.keyboard.press("Control+Enter")
    page.wait_for_timeout(2500)
    page_text = (page.inner_text("body") or "").lower()
    if "message sent" in page_text or "undo" in page_text:
        return True
    return True


UPLOADING_WORDS = ("uploading", "attaching")


def attachment_ready(compose_text: str, filename: str) -> bool:
    """True once the compose window shows the file chip and no upload is in progress."""
    text = (compose_text or "").lower()
    return filename.lower() in text and not any(w in text for w in UPLOADING_WORDS)


def _compose_scope(page):
    try:
        dialogs = page.locator('div[role="dialog"]').filter(has=page.locator('input[name="subjectbox"]'))
        if dialogs.count():
            return dialogs.last
    except Exception:
        pass
    return page


def attach_resume_verified(page, resume: Path, timeout_ms: int = 45000) -> bool:
    """Attach via Gmail's paperclip (file chooser), falling back to the hidden file input,
    then wait until the attachment chip with the file name appears."""
    scope = _compose_scope(page)
    started = False
    try:
        btn = scope.locator('[aria-label^="Attach files"], [data-tooltip^="Attach files"]')
        if btn.count():
            with page.expect_file_chooser(timeout=6000) as chooser:
                btn.first.click()
            chooser.value.set_files(str(resume))
            started = True
    except Exception as exc:
        print(f"    attach via paperclip failed: {exc}")
    if not started:
        try:
            inputs = page.locator('input[type="file"]')
            if inputs.count():
                inputs.last.set_input_files(str(resume))
                started = True
        except Exception as exc:
            print(f"    attach via file input failed: {exc}")
    if not started:
        return False
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            text = scope.inner_text()
        except Exception:
            text = ""
        if attachment_ready(text, resume.name):
            return True
        page.wait_for_timeout(1000)
    return False
