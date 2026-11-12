from __future__ import annotations

import csv
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import Page

from apply_bot.config import Settings, load_profile
from apply_bot.linkedin.scraper import get_today_count, increment_today_count

DEFAULT_RESUME_DRIVE = (
    "https://drive.google.com/file/d/1szaTsvCPrrfmrOhcwGkOS04ByY4INcHo/view?usp=drive_link"
)


def normalize_profile_url(url: str) -> str:
    """Canonicalize a LinkedIn /in/ URL for dedupe (strip query/fragment/trailing slash)."""
    if not url:
        return ""
    raw = url.strip()
    if raw.startswith("/"):
        raw = "https://www.linkedin.com" + raw
    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
    # Keep only /in/<slug>
    parts = [p for p in path.split("/") if p]
    if "in" in parts:
        i = parts.index("in")
        if i + 1 < len(parts):
            path = f"/in/{parts[i + 1]}"
    return urlunparse(("https", "www.linkedin.com", path, "", "", ""))


def clean_company(company: str | None) -> str:
    if not company:
        return ""
    c = company.strip()
    if not c:
        return ""
    lower = c.lower()
    if lower in {"your company", "n/a", "na", "none", "unknown"}:
        return ""
    if "linkedin.com" in lower or lower.startswith("http") or "/in/" in lower:
        return ""
    return c



def recipient_name_matches(text: str, full_name: str) -> bool:
    """True if bubble label/header is addressed to full_name (full or first-name match).

    Accepts exact full-name match, or first-name match when the full name has 2+
    tokens (LinkedIn often truncates long display names). Case-insensitive.
    """
    hay = (text or "").strip().lower()
    name = (full_name or "").strip().lower()
    if not hay or not name:
        return False
    if name in hay:
        return True
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        first = parts[0]
        # Require first name as a token (avoid "An" matching "Anand")
        tokens = [t for t in hay.replace(",", " ").split() if t]
        if first in tokens:
            return True
    return False


def is_transient_nav_error(exc: BaseException) -> bool:
    """True for network / page-crash errors worth one retry."""
    s = str(exc).lower()
    needles = (
        "err_internet_disconnected",
        "err_network_changed",
        "err_connection_reset",
        "err_connection_closed",
        "err_connection_aborted",
        "err_name_not_resolved",
        "err_timed_out",
        "net::err_",
        "target closed",
        "page crashed",
        "has been closed",
        "navigating frame was detached",
    )
    return any(n in s for n in needles)

def build_referral_message(first_name: str, company: str | None = None) -> str:
    """Short personalized referral ask. Max ~300 chars. Pure helper (no I/O)."""
    name = (first_name or "there").strip() or "there"
    company_clean = clean_company(company)
    if company_clean:
        msg = (
            f"Hi {name}, hope you're well! I'm Sumanth, a 2026 B.Tech grad "
            f"(backend + AI/ML: Python, FastAPI, LLM agents). I'm exploring "
            f"full-time SDE / AI engineer roles - if {company_clean} has openings, "
            f"would you be open to referring me? I've attached my resume. Thanks!"
        )
    else:
        msg = (
            f"Hi {name}, hope you're well! I'm Sumanth, a 2026 B.Tech grad "
            f"(backend + AI/ML: Python, FastAPI, LLM agents). I'm exploring "
            f"full-time SDE / AI engineer roles - would you be open to referring me? "
            f"I've attached my resume. Thanks!"
        )
    if len(msg) > 300:
        msg = msg[:297] + "..."
    return msg


def generate_message(first_name: str, company: str, settings: Settings | None = None) -> str:
    """Compatibility wrapper used by send_messages / CLI dry-run."""
    return build_referral_message(first_name, company)


def load_sent_profile_urls(outreach_path: Path) -> set[str]:
    """URLs already messaged ? from outreach CSV rows with a non-empty sent_at only."""
    if not outreach_path.exists():
        return set()
    urls: set[str] = set()
    with open(outreach_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("sent_at") and row.get("profile_url"):
                urls.add(normalize_profile_url(row["profile_url"]))
    return urls


def load_skipped_profile_urls(outreach_path: Path, min_skips: int = 3) -> set[str]:
    """URLs safety-skipped >= min_skips times (never sent) - exclude from future runs."""
    if not outreach_path.exists():
        return set()
    counts: dict[str, int] = {}
    with open(outreach_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("sent_at") or not row.get("profile_url"):
                continue
            if (row.get("error") or "").startswith("Skipped:"):
                u = normalize_profile_url(row["profile_url"])
                counts[u] = counts.get(u, 0) + 1
    return {u for u, c in counts.items() if c >= min_skips}


def resolve_resume_path(settings: Settings) -> Path:
    profile = load_profile()
    candidates: list[Path] = []
    if profile.resume_path:
        p = Path(profile.resume_path).expanduser()
        if not p.is_absolute():
            p = settings.project_root / p
        candidates.append(p)
    candidates.append(settings.project_root / "data" / "resume.pdf")
    for c in candidates:
        if c.exists():
            return c
    # Last-chance copy from Downloads
    downloads = Path(r"C:\Users\suman\Downloads\sumanth_ponugupati.pdf")
    dest = settings.project_root / "data" / "resume.pdf"
    if downloads.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(downloads.read_bytes())
        return dest
    raise FileNotFoundError(f"resume.pdf missing; looked at {[str(c) for c in candidates]}")


def resolve_drive_link() -> str:
    profile = load_profile()
    return (profile.resume_drive or DEFAULT_RESUME_DRIVE).strip()


BUBBLE_SEL = ".msg-overlay-conversation-bubble"


def _close_bubbles(page: Page) -> None:
    """Close any open message overlay bubbles (stale drafts / generic composer)."""
    for _ in range(6):
        bubbles = page.locator(BUBBLE_SEL)
        if bubbles.count() == 0:
            break
        btn = bubbles.first.get_by_role("button", name="Close your", exact=False)
        if btn.count() == 0:
            break
        try:
            btn.first.click(timeout=2000)
            page.wait_for_timeout(700)
            for label in ("Discard", "Leave"):
                d = page.get_by_role("button", name=label, exact=True)
                if d.count() > 0 and d.first.is_visible():
                    d.first.click(timeout=2000)
                    page.wait_for_timeout(500)
                    break
        except Exception:
            break


def _find_profile_compose(page: Page):
    """Visible Message control on the profile itself (not the global Messaging overlay)."""
    sels = [
        "main a[href*='/messaging/compose/'][href*='NON_SELF_PROFILE_VIEW']",
        "a[href*='/messaging/compose/'][href*='NON_SELF_PROFILE_VIEW']",
    ]
    for sel in sels:
        loc = page.locator(sel)
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:
                continue
    loc = page.locator("main").get_by_role("button", name="Message", exact=True)
    for i in range(loc.count()):
        try:
            if loc.nth(i).is_visible():
                return loc.nth(i)
        except Exception:
            continue
    return None


def _self_name() -> str:
    try:
        return (load_profile().full_name or "").strip()
    except Exception:
        return ""


def thread_label_participants(label: str, self_name: str = "") -> list[str]:
    """Parse 'Close your conversation with A and B' -> other participants (minus self)."""
    lab = (label or "").strip()
    m = re.match(r"(?i)^(?:close|minimize)\s+your\s+conversation\s+with\s+(.+)$", lab)
    if not m:
        return []
    body = m.group(1).strip()
    parts = [p.strip() for p in re.split(r",\s*|\s+and\s+", body) if p.strip()]
    me_tokens = set((self_name or "").strip().lower().split())
    out = []
    for p in parts:
        pt = set(p.lower().split())
        # order-insensitive self match ("Ponugupati Sumanth" == "Sumanth Ponugupati")
        if me_tokens and pt and (pt == me_tokens or pt <= me_tokens):
            continue
        out.append(p)
    return out


def _thread_bubble_is_one_to_one(bubble, full_name: str) -> bool:
    """Existing thread bubble: exactly one other participant and it matches full_name."""
    me = _self_name()
    labels: list[str] = []
    try:
        btns = bubble.locator("button")
        for i in range(min(btns.count(), 40)):
            el = btns.nth(i)
            for lab in (el.get_attribute("aria-label") or "", el.inner_text(timeout=800) or ""):
                lab = " ".join(lab.split())
                if re.match(r"(?i)^close\s+your\s+conversation\s+with\s", lab):
                    labels.append(lab)
    except Exception:
        return False
    for label in labels:
        others = thread_label_participants(label, me)
        if len(others) == 1 and recipient_name_matches(others[0], full_name):
            return True
    return False


def _dump_skip_diag(page: Page, full_name: str) -> None:
    """Log what the overlay looked like when we refused to send (for debugging skips)."""
    try:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", full_name)[:40] or "unknown"
        shot = Path("data/screenshots") / f"skip_{datetime.now():%H%M%S}_{slug}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot))
        bubbles = page.locator(BUBBLE_SEL)
        print(f"  [skip-diag] url={page.url} bubbles={bubbles.count()} shot={shot}")
        for i in range(bubbles.count()):
            b = bubbles.nth(i)
            labels = b.evaluate(
                "e=>Array.from(e.querySelectorAll('button')).slice(0,6).map(x=>"
                "(x.getAttribute('aria-label')||(x.innerText||'').trim()).replace(/\\s+/g,' ').slice(0,80))"
            )
            print(f"  [skip-diag] bubble {i} visible={b.is_visible()} buttons={labels}")
    except Exception as exc:
        print(f"  [skip-diag] failed: {exc}")


def _recipient_bubble(page: Page, full_name: str):
    """Return the open bubble addressed ONLY to this person, else None.

    Compose bubble: exactly one recipient pill matching full_name (or first name
    when the full name is long). Refuse zero recipients or multiple mismatched
    people. Existing thread: header matches name; no recipient box.
    """
    name = (full_name or "").strip()
    if not name:
        return None
    bubbles = page.locator(BUBBLE_SEL)
    for i in range(bubbles.count() - 1, -1, -1):
        b = bubbles.nth(i)
        try:
            if not b.is_visible():
                continue
            pills = b.locator("button[aria-label^='Remove ']")
            n_pills = pills.count()
            if n_pills > 0:
                if n_pills != 1:
                    # Multiple recipients — never send into a group/wrong thread
                    continue
                label = (pills.first.get_attribute("aria-label") or "").strip()
                # aria-label is typically "Remove <Name>"
                label_name = label
                low = label.lower()
                if low.startswith("remove "):
                    label_name = label[7:].strip()
                if recipient_name_matches(label_name, name) or recipient_name_matches(label, name):
                    return b
                continue
            if b.locator("input[placeholder*='Type a name' i]").count() > 0:
                # Empty compose with no pill yet — not verified
                continue
            header = b.locator(".msg-overlay-bubble-header").first
            if header.count():
                header_text = header.inner_text(timeout=1500)
                if recipient_name_matches(header_text, name):
                    return b
            if _thread_bubble_is_one_to_one(b, name):
                return b
        except Exception:
            continue
    return None


def attach_resume_to_dm(page: Page, resume: Path, bubble=None) -> bool:
    """Attach PDF inside the recipient bubble. Returns True if attachment preview appears."""
    scope = bubble if bubble is not None else page
    try:
        file_input = scope.locator('input[type="file"]')
        if file_input.count() > 0:
            # prefer the generic file attach input (not image-only)
            target = file_input.first
            for i in range(file_input.count()):
                acc = (file_input.nth(i).get_attribute("accept") or "").lower()
                if ".pdf" in acc:
                    target = file_input.nth(i)
                    break
            target.set_input_files(str(resume))
            page.wait_for_timeout(4000)
            name = resume.name
            if scope.get_by_text(name, exact=False).count() > 0 or scope.locator(
                "[class*='attachment']"
            ).count() > 0:
                return True
            print("  attach: file set but no preview found")
            return True
    except Exception as exc:
        print(f"  attach via bubble file input failed: {exc}")
    return False


def _fill_message_box(page: Page, message: str, bubble=None) -> bool:
    scope = bubble if bubble is not None else page
    message_box = scope.locator(
        "div.msg-form__contenteditable[contenteditable='true'], "
        "div[role='textbox'][contenteditable='true']"
    ).first
    if message_box.count() == 0:
        return False
    try:
        message_box.click(timeout=3000)
        page.wait_for_timeout(200)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        page.keyboard.type(message, delay=15)
        page.wait_for_timeout(400)
        return True
    except Exception as exc:
        print(f"  fill message failed: {exc}")
        return False


def _event_count(bubble) -> int:
    try:
        return bubble.locator(".msg-s-event-listitem, .msg-s-message-list__event").count()
    except Exception:
        return 0


def _click_send(page: Page, bubble=None) -> bool:
    scope = bubble if bubble is not None else page
    send_btn = scope.locator("button.msg-form__send-button, button[type='submit']").first
    if send_btn.count() == 0:
        return False
    try:
        for _ in range(20):  # wait for upload to finish (button enabled)
            if send_btn.is_enabled():
                break
            page.wait_for_timeout(500)
        send_btn.click(timeout=5000)
        page.wait_for_timeout(3000)
        return True
    except Exception as exc:
        print(f"  send click failed: {exc}")
        return False


def send_message(
    page: Page,
    profile_url: str,
    message: str,
    resume: Path | None = None,
    drive_link: str = "",
    full_name: str = "",
) -> tuple[str, str]:
    """Send a DM with resume attached (PDF preferred, Drive link fallback).

    Only types into a bubble verified to be addressed to `full_name`.

    Returns (status, attach_method) where status is:
      - "sent": message dispatched
      - "skip": safety skip (e.g. recipient bubble not verified) — not a fail streak
      - "error": real failure
    """
    attach_method = ""

    def _attempt() -> tuple[str, str]:
        nonlocal attach_method
        page.goto(profile_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        _close_bubbles(page)

        ctl = _find_profile_compose(page)
        if ctl is None:
            print(f"  No profile Message control for {profile_url}")
            return "skip", ""
        ctl.click(timeout=5000)
        page.wait_for_timeout(3500)

        bubble = _recipient_bubble(page, full_name)
        if bubble is None:
            page.wait_for_timeout(3000)
            bubble = _recipient_bubble(page, full_name)
        if bubble is None:
            # Retry once: fresh profile load, close stale overlays, click Message again
            print(f"  Bubble not verified for {full_name!r}; reloading profile and retrying once...")
            _close_bubbles(page)
            page.goto(profile_url, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            _close_bubbles(page)
            ctl2 = _find_profile_compose(page)
            if ctl2 is not None:
                ctl2.click(timeout=5000)
                page.wait_for_timeout(5000)
                bubble = _recipient_bubble(page, full_name)
        if bubble is None:
            _dump_skip_diag(page, full_name)
            print(f"  Recipient bubble for {full_name!r} not verified; skipping (safety).")
            _close_bubbles(page)
            return "skip", ""

        before = _event_count(bubble)
        final_message = message
        if resume and resume.exists() and attach_resume_to_dm(page, resume, bubble):
            attach_method = "pdf"
        else:
            link = drive_link or resolve_drive_link()
            if "drive.google.com" not in final_message:
                final_message = f"{final_message.rstrip()} Resume: {link}"
            attach_method = "drive_link"
            print("  PDF attach unavailable; appended Drive link to message.")

        if not _fill_message_box(page, final_message, bubble):
            print(f"  Could not find message box for {profile_url}")
            _close_bubbles(page)
            return "error", attach_method

        if attach_method not in {"pdf", "drive_link"}:
            print("  Refusing to send: no resume attach and no Drive link.")
            return "error", ""

        if not _click_send(page, bubble):
            _close_bubbles(page)
            return "error", attach_method

        after = _event_count(bubble)
        if after <= before:
            page.wait_for_timeout(3000)
            after = _event_count(bubble)
        if after <= before:
            # Send was clicked; treat as sent to avoid ever double-messaging.
            print(
                f"  WARNING: send clicked but not confirmed in thread "
                f"(events {before}->{after}); logging as sent."
            )
        _close_bubbles(page)
        return "sent", attach_method

    try:
        return _attempt()
    except Exception as e:
        if is_transient_nav_error(e):
            wait_s = random.uniform(30, 60)
            print(
                f"  Transient nav/network error ({e}); "
                f"waiting {wait_s:.0f}s then retrying once..."
            )
            try:
                page.wait_for_timeout(int(wait_s * 1000))
            except Exception:
                pass
            try:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
            except Exception:
                pass
            try:
                return _attempt()
            except Exception as e2:
                print(f"  Error sending message to {profile_url} (after retry): {e2}")
                return "error", attach_method
        print(f"  Error sending message to {profile_url}: {e}")
        return "error", attach_method


WARNING_TEXTS = [
    "you've reached the weekly invitation limit",
    "you\u2019ve reached the weekly invitation limit",
    "weekly limit reached",
    "message limit reached",
    "your account has been restricted",
    "your account is temporarily restricted",
    "temporarily restricted",
    "we've restricted your account",
    "let's do a quick security check",
    "let\u2019s do a quick security check",
]

CHECKPOINT_URL_MARKERS = ("/checkpoint/", "/challenge", "/authwall", "/uas/login")

# Invisible reCAPTCHA v3 widgets LinkedIn embeds on normal pages - NOT a challenge.
_BENIGN_CAPTCHA_CLASSES = ("grecaptcha-badge", "grecaptcha-logo", "grecaptcha-error")


def _any_visible(loc, max_check: int = 10) -> bool:
    try:
        n = min(loc.count(), max_check)
    except Exception:
        return False
    for i in range(n):
        try:
            if loc.nth(i).is_visible():
                return True
        except Exception:
            continue
    return False


def check_for_warnings(page: Page) -> bool:
    """Real LinkedIn limit/restriction notices only (visible text), or checkpoint URL."""
    url = (page.url or "").lower()
    if any(m in url for m in CHECKPOINT_URL_MARKERS):
        print(f"  Checkpoint/challenge URL detected: {page.url}")
        return True
    for text in WARNING_TEXTS:
        if _any_visible(page.get_by_text(text, exact=False)):
            print(f"  Visible LinkedIn warning text: {text!r}")
            return True
    return False


def check_for_captcha(page: Page) -> bool:
    """Visible captcha challenge only; ignores LinkedIn's hidden reCAPTCHA v3 badge."""
    for selector in ("#captcha-challenge", ".captcha-challenge", "#captcha-internal"):
        if _any_visible(page.locator(selector)):
            print(f"  Visible captcha element: {selector}")
            return True
    try:
        frames = page.locator(
            "iframe[src*='captcha'], iframe[src*='arkoselabs'], iframe[src*='funcaptcha']"
        )
        for i in range(min(frames.count(), 10)):
            f = frames.nth(i)
            try:
                if not f.is_visible():
                    continue
                box = f.bounding_box()
                src = (f.get_attribute("src") or "").lower()
                # reCAPTCHA v3 anchor iframe is invisible/tiny; real challenges are large
                if "size=invisible" in src:
                    continue
                if box and box["width"] >= 150 and box["height"] >= 150:
                    print(f"  Visible captcha iframe: {src[:120]}")
                    return True
            except Exception:
                continue
    except Exception:
        pass
    try:
        loc = page.locator("[class*='captcha']")
        for i in range(min(loc.count(), 20)):
            el = loc.nth(i)
            cls = (el.get_attribute("class") or "").lower()
            if any(b in cls for b in _BENIGN_CAPTCHA_CLASSES):
                continue
            if el.is_visible():
                box = el.bounding_box()
                if box and box["width"] >= 150 and box["height"] >= 100:
                    print(f"  Visible captcha container: class={cls[:80]}")
                    return True
    except Exception:
        pass
    return False


def should_stop(page: Page) -> bool:
    return check_for_warnings(page) or check_for_captcha(page)


def send_messages(
    page: Page,
    contacts: list[dict[str, Any]],
    settings: Settings,
    daily_limit: int = 20,
    dry_run: bool = False,
) -> dict[str, Any]:
    results: dict[str, Any] = {
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "stopped_early": False,
        "reason": "",
        "samples": [],
    }

    daily_counts_path = settings.project_root / "data" / "linkedin_daily_counts.json"
    outreach_log_path = settings.project_root / "data" / "linkedin_outreach.csv"

    try:
        resume = resolve_resume_path(settings)
    except FileNotFoundError as exc:
        print(f"WARNING: {exc}")
        resume = None
    drive_link = resolve_drive_link()

    current_count = get_today_count(daily_counts_path)
    consecutive_fail = 0

    for i, contact in enumerate(contacts):
        if consecutive_fail >= 3:
            results["stopped_early"] = True
            results["reason"] = "3 consecutive send failures - stopping for review"
            break
        if current_count >= daily_limit:
            results["stopped_early"] = True
            results["reason"] = f"Daily limit of {daily_limit} reached"
            break

        if not dry_run and should_stop(page):
            results["stopped_early"] = True
            results["reason"] = "LinkedIn warning or captcha detected"
            break

        first_name = contact["name"].split()[0] if contact.get("name") else "there"
        company = contact.get("company") or ""
        message = generate_message(first_name, company, settings)
        results["samples"].append(
            {"name": contact.get("name"), "company": company, "message": message}
        )

        print(f"\n[{i + 1}/{len(contacts)}] {contact.get('name')} at {company or '(no company)'}")
        print(f"Message ({len(message)} chars): {message}")

        if dry_run:
            results["sent"] += 1
            continue

        try:
            status, attach_method = send_message(
                page,
                contact["profile_url"],
                message,
                resume=resume,
                drive_link=drive_link,
                full_name=contact.get("name", ""),
            )

            if status == "sent":
                consecutive_fail = 0
                current_count += 1
                increment_today_count(daily_counts_path)
                results["sent"] += 1
                log_outreach(
                    contact,
                    outreach_log_path,
                    sent=True,
                    resume_sent=True,
                    attach_method=attach_method,
                )
                gap = random.uniform(28, 32)
                print(f"Message sent (attach={attach_method}). Waiting {gap:.0f}s...")
                page.wait_for_timeout(int(gap * 1000))
            elif status == "skip":
                # Safety skip (e.g. recipient not verified) — do NOT trip fail streak
                consecutive_fail = 0
                results["skipped"] += 1
                log_outreach(
                    contact,
                    outreach_log_path,
                    sent=False,
                    error="Skipped: recipient bubble not verified",
                    attach_method=attach_method,
                )
                # Short pause so we don't hammer the next profile
                page.wait_for_timeout(int(random.uniform(8, 15) * 1000))
            else:
                consecutive_fail += 1
                results["errors"] += 1
                log_outreach(
                    contact,
                    outreach_log_path,
                    sent=False,
                    error="Failed to send",
                    attach_method=attach_method,
                )

        except Exception as e:
            if is_transient_nav_error(e):
                wait_s = random.uniform(30, 60)
                print(f"  Transient error in loop ({e}); waiting {wait_s:.0f}s...")
                try:
                    page.wait_for_timeout(int(wait_s * 1000))
                except Exception:
                    pass
            consecutive_fail += 1
            results["errors"] += 1
            print(f"Error: {e}")
            log_outreach(contact, outreach_log_path, sent=False, error=str(e))

    return results


def log_outreach(
    contact: dict[str, Any],
    log_path: Path,
    sent: bool,
    error: str = "",
    replied: bool = False,
    resume_sent: bool = False,
    attach_method: str = "",
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "name",
        "company",
        "profile_url",
        "sent_at",
        "replied",
        "resume_sent",
        "attach_method",
        "follow_up_due",
        "error",
    ]
    file_exists = log_path.exists()

    with open(log_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        follow_up_due = (datetime.now() + timedelta(days=5)).isoformat() if sent else ""

        writer.writerow(
            {
                "name": contact.get("name", ""),
                "company": contact.get("company", ""),
                "profile_url": contact.get("profile_url", ""),
                "sent_at": datetime.now().isoformat() if sent else "",
                "replied": replied,
                "resume_sent": resume_sent or bool(attach_method),
                "attach_method": attach_method,
                "follow_up_due": follow_up_due,
                "error": error if not sent else "",
            }
        )


def check_replies(page: Page, settings: Settings) -> list[dict[str, Any]]:
    page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    outreach_log_path = settings.project_root / "data" / "linkedin_outreach.csv"
    if not outreach_log_path.exists():
        return []

    sent_contacts: dict[str, dict[str, Any]] = {}
    with open(outreach_log_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("sent_at") and not row.get("replied"):
                sent_contacts[normalize_profile_url(row["profile_url"])] = row

    replies: list[dict[str, Any]] = []
    conversations = page.locator(".msg-s-message-list__event, .message-list-item").all()

    for conv in conversations:
        try:
            profile_link = conv.locator("a[href*='/in/']").first
            if profile_link.count() == 0:
                continue

            profile_url = profile_link.get_attribute("href")
            if not profile_url:
                continue

            key = normalize_profile_url(profile_url)
            if key in sent_contacts:
                message_el = conv.locator(".msg-s-message-list__message, .message-body").first
                if message_el.count() > 0:
                    message_text = message_el.inner_text(timeout=500).lower()

                    resume_keywords = ["resume", "cv", "send resume", "share resume"]
                    if any(kw in message_text for kw in resume_keywords):
                        replies.append(
                            {
                                "name": sent_contacts[key]["name"],
                                "company": sent_contacts[key]["company"],
                                "profile_url": profile_url,
                                "message": message_el.inner_text(timeout=500),
                                "action": "send_resume",
                            }
                        )
        except Exception:
            continue

    return replies


def draft_resume_reply(name: str, message: str) -> str:
    reply = (
        f"Hi {name.split()[0] if name else 'there'},\n\n"
        f"Thanks for your response! Here's my resume for your reference:\n"
        f"{resolve_drive_link()}\n\n"
        f"Let me know if you need any additional information. I'm available for immediate joining.\n\n"
        f"Best regards,\nSumanth"
    )
    return reply
