"""Optional daily Naukri profile 'touch': re-save the resume headline. OFF by default (settings.naukri_profile_touch)."""
from __future__ import annotations

from playwright.sync_api import Page

PROFILE_URL = "https://www.naukri.com/mnjuser/profile"


def naukri_profile_touch(page: Page, headline: str, *, enabled: bool, dry_run: bool = True) -> str:
    if not enabled:
        return "disabled (set naukri_profile_touch: true in config/settings.yaml)"
    if not headline.strip():
        return "skipped: profile.yaml naukri_headline is empty"
    page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    if "nlogin" in page.url:
        return "needs_login"
    section = page.locator("#lazyResumeHead, .resumeHeadline, [class*='resumeHeadline']").first
    try:
        section.locator(".edit, [class*='edit']").first.click(timeout=5000)
        page.wait_for_timeout(1000)
        box = page.locator("textarea#resumeHeadlineTxt, form textarea").first
        box.fill(headline.strip()[:250])
        if dry_run:
            return "dry-run: headline filled, not saved"
        page.get_by_role("button", name="Save").first.click(timeout=5000)
        page.wait_for_timeout(1500)
        return "saved"
    except Exception as exc:
        return f"failed: {exc}"
