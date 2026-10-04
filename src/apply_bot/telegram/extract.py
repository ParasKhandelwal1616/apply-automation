from __future__ import annotations

import hashlib
import re

from playwright.sync_api import Locator, Page

from apply_bot.config import Settings
from apply_bot.models import ExtractedMessage
from apply_bot.telegram.browser import jump_to_newest

MONTH_RE = re.compile(
    r"\b(?:today|yesterday|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2})\b",
    re.I,
)

BUBBLE_SELECTORS = [
    ".messages-container .message",
    ".bubbles-inner .message",
    "#column-center .message",
    ".Message",
    "[class*='message-list'] [class*='Message']",
    ".text-content",
]


def _fingerprint(text: str, hrefs: list[str]) -> str:
    date_hint = ""
    date_match = re.search(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{1,2}:\d{2}|\d{1,2}/\d{1,2})\b",
        text,
        re.I,
    )
    if date_match:
        date_hint = date_match.group(0).lower()
    raw = f"{date_hint}|{text[:80].strip().lower()}|{'|'.join(sorted(hrefs))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _bubble_locators(page: Page) -> Locator:
    for selector in BUBBLE_SELECTORS:
        loc = page.locator(selector)
        try:
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return page.locator(".message")


def _innermost_text(text: str) -> str:
    markers = (
        "forwarded from",
        "forwarded message",
    )
    lowered = text.lower()
    last = 0
    for marker in markers:
        idx = lowered.rfind(marker)
        if idx > last:
            last = idx
    if last:
        cut = text[last:]
        newline = cut.find("\n")
        if newline != -1:
            return cut[newline + 1 :].strip() or text.strip()
    return text.strip()


def _scroll_chat_up(page: Page) -> None:
    try:
        page.evaluate(
            """() => {
              const sels = [
                '.bubbles .scrollable-y',
                '.scrollable-y.scrollable',
                '.bubbles',
                '.bubbles-inner',
                '.messages-container',
                '#column-center .scrollable',
                '.scrollable-y',
                '#column-center'
              ];
              for (const s of sels) {
                const el = document.querySelector(s);
                if (!el) continue;
                if (el.scrollHeight > el.clientHeight + 10) {
                  el.scrollTop = Math.max(0, el.scrollTop - Math.max(el.clientHeight * 2, 5000));
                  return el.scrollTop;
                }
              }
              window.scrollBy(0, -4000);
              return -1;
            }"""
        )
    except Exception:
        pass
    try:
        box = None
        for selector in (".bubbles .scrollable-y", ".bubbles", "#column-center"):
            loc = page.locator(selector)
            if loc.count() > 0:
                box = loc.first.bounding_box()
                if box:
                    break
        if box:
            page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.45)
            page.mouse.wheel(0, -9000)
        else:
            page.mouse.wheel(0, -9000)
    except Exception:
        try:
            page.mouse.wheel(0, -9000)
        except Exception:
            pass
    try:
        page.keyboard.press("PageUp")
    except Exception:
        pass


def _js_visible_dates(page: Page) -> list[str]:
    try:
        data = page.evaluate(
            """() => {
              const sels = [
                '.bubble-date-inner',
                '.bubble-date',
                '.bubbles-date',
                '.service-msg',
                '[class*="bubble-date"]',
                '.date'
              ];
              const out = [];
              for (const s of sels) {
                document.querySelectorAll(s).forEach((el) => {
                  const t = (el.innerText || '').trim();
                  if (t && t.length < 40) out.push(t);
                });
              }
              return [...new Set(out)];
            }"""
        )
        return [str(x) for x in data] if isinstance(data, list) else []
    except Exception:
        return []


def _collect_date_labels(page: Page, extracted: list[ExtractedMessage], seen: list[str]) -> None:
    for raw in _js_visible_dates(page):
        match = MONTH_RE.search(raw)
        if match:
            label = match.group(0).strip()
            if label not in seen:
                seen.append(label)
    for msg in extracted:
        match = MONTH_RE.search(msg.text[:200])
        if match:
            label = match.group(0).strip()
            if label not in seen:
                seen.append(label)


def _js_visible_posts(page: Page) -> list[dict]:
    try:
        data = page.evaluate(
            """() => {
              const nodes = [
                ...document.querySelectorAll(
                  '.bubbles-inner .message, #column-center .message, .messages-container .message, .Message'
                )
              ];
              return nodes.map((el) => {
                const text = (el.innerText || '').trim();
                const hrefs = [...el.querySelectorAll('a[href]')]
                  .map((a) => (a.getAttribute('href') || '').trim())
                  .filter((h) => h.startsWith('http') || h.startsWith('mailto:'));
                return { text, hrefs: [...new Set(hrefs)] };
              }).filter((x) => x.text.length > 8 || x.hrefs.length);
            }"""
        )
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _harvest_visible(
    page: Page,
    settings: Settings,
    seen_fp: set[str],
    extracted: list[ExtractedMessage],
    limit: int,
) -> int:
    added = 0
    rows = _js_visible_posts(page)
    if not rows:
        bubbles = _bubble_locators(page)
        try:
            total = bubbles.count()
        except Exception:
            total = 0
        for i in range(total):
            if len(extracted) >= limit:
                break
            bubble = bubbles.nth(i)
            try:
                text = _innermost_text(bubble.inner_text(timeout=400) or "")
            except Exception:
                continue
            hrefs: list[str] = []
            try:
                for handle in bubble.locator("a[href]").all():
                    href = (handle.get_attribute("href") or "").strip()
                    if href.startswith(("http://", "https://", "mailto:")):
                        hrefs.append(href)
            except Exception:
                pass
            rows.append({"text": text, "hrefs": hrefs})
    for row in rows:
        if len(extracted) >= limit:
            break
        text = _innermost_text(str(row.get("text") or ""))
        hrefs = [str(h) for h in (row.get("hrefs") or []) if h]
        if not text.strip() and not hrefs:
            continue
        fp = _fingerprint(text, hrefs)
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        extracted.append(
            ExtractedMessage(
                fingerprint=fp,
                text=text,
                hrefs=hrefs,
                screenshot_path=None,
                needs_vision=len(text.strip()) < settings.min_text_chars,
                preview=re.sub(r"\s+", " ", text)[:160],
            )
        )
        added += 1
    return added


def extract_messages(page: Page, settings: Settings, limit: int) -> list[ExtractedMessage]:
    settings.screenshot_dir.mkdir(parents=True, exist_ok=True)
    jump_to_newest(page)
    for _ in range(10):
        try:
            if page.get_by_text("Referral Alert", exact=False).count() > 0:
                break
        except Exception:
            pass
        page.wait_for_timeout(600)

    seen_fp: set[str] = set()
    extracted: list[ExtractedMessage] = []
    date_labels: list[str] = []
    _harvest_visible(page, settings, seen_fp, extracted, limit)
    _collect_date_labels(page, extracted, date_labels)
    if date_labels:
        print(f"    extract dates after jump-to-newest: {', '.join(date_labels[:8])}")

    scrolls = 700 if limit >= 250 else 500 if limit >= 150 else 350 if limit >= 100 else 80 if limit > 40 else 24
    stagnant = 0
    last_len = len(extracted)
    for step in range(scrolls):
        if len(extracted) >= limit:
            break
        _scroll_chat_up(page)
        page.wait_for_timeout(450 if step % 3 else 900)
        added = _harvest_visible(page, settings, seen_fp, extracted, limit)
        _collect_date_labels(page, extracted, date_labels)
        if added:
            stagnant = 0
            last_len = len(extracted)
            if last_len % 25 == 0 or added >= 5:
                tail = f" dates={date_labels[0]}…{date_labels[-1]}" if date_labels else ""
                print(f"    extract progress: {last_len} unique posts{tail}")
            continue
        stagnant += 1
        if stagnant in {8, 16, 24}:
            page.wait_for_timeout(1400)
            added = _harvest_visible(page, settings, seen_fp, extracted, limit)
            if added:
                stagnant = 0
                last_len = len(extracted)
                continue
        if stagnant >= 50:
            break
    newest = date_labels[0] if date_labels else "?"
    oldest = date_labels[-1] if date_labels else "?"
    print(
        f"Extracted {len(extracted)} unique posts (limit {limit}); "
        f"newest={newest} oldest={oldest}"
    )
    return extracted
