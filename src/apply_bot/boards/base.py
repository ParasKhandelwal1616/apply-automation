from __future__ import annotations

from playwright.sync_api import Page

LOGIN_HINTS = (
    "log in",
    "login",
    "sign in",
    "sign up",
    "register",
    "scan the qr",
)
CAPTCHA_HINTS = (
    "captcha",
    "are you a robot",
    "verify you are human",
    "unusual traffic",
    "security check",
)


class BoardStop(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def page_text(page: Page) -> str:
    try:
        return page.inner_text("body") or ""
    except Exception:
        return ""


def blocked_reason(text: str) -> str | None:
    lowered = text.lower()
    if any(hint in lowered for hint in CAPTCHA_HINTS):
        return "captcha"
    return None


def looks_like_login(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in LOGIN_HINTS) and "apply" not in lowered[:80]


def upload_resume(page: Page, resume_path: str) -> None:
    if not resume_path:
        return
    loc = page.locator("input[type='file']")
    try:
        if loc.count() == 0:
            return
        loc.first.set_input_files(resume_path)
    except Exception:
        return


def click_apply(page: Page) -> bool:
    labels = ("Apply", "Easy Apply", "Apply now", "I'm interested")
    for label in labels:
        loc = page.get_by_role("button", name=label, exact=False)
        try:
            if loc.count() == 0:
                loc = page.get_by_role("link", name=label, exact=False)
            if loc.count() == 0 or not loc.first.is_visible(timeout=800):
                continue
            loc.first.click(timeout=4000)
            page.wait_for_timeout(1200)
            return True
        except Exception:
            continue
    return False


def confirmed(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "application submitted",
        "successfully applied",
        "you have applied",
        "applied successfully",
        "your application has been submitted",
        "thanks for applying",
        "thank you for applying",
    )
    return any(marker in lowered for marker in markers)
