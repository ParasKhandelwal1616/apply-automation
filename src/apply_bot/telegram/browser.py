from __future__ import annotations

import re
import time

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from apply_bot.config import Settings

CHAT_URL_RE = re.compile(
    r"^(https://web\.telegram\.org/[ka]/#)(-?\d+)(?:[/_]\d+.*)?$",
    re.I,
)


def chat_root_url(url: str) -> str | None:
    """Keep the chat hash, drop a message permalink that pins mid-history."""
    text = (url or "").strip()
    if not text.startswith("https://web.telegram.org/"):
        return None
    match = CHAT_URL_RE.match(text)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    if re.match(r"^https://web\.telegram\.org/[ka]/?$", text, re.I):
        return text.rstrip("/") + "/"
    return None


def jump_to_newest(page: Page) -> None:
    """Land on the latest messages. Telegram restores last-read (often Aug 27)."""
    go_down = [
        ".bubbles-go-down",
        ".chat-go-down",
        ".go-down",
        "[class*='bubbles-go-down']",
        "[class*='go-down']",
        "[class*='GoDown']",
        "[class*='scroll-down']",
        "[class*='ScrollDown']",
        "button[aria-label*='bottom' i]",
        "button[aria-label*='Go to' i]",
    ]
    for attempt in range(12):
        clicked = False
        for selector in go_down:
            loc = page.locator(selector)
            try:
                if loc.count() == 0 or not loc.first.is_visible(timeout=250):
                    continue
                loc.first.click(timeout=800)
                clicked = True
                break
            except Exception:
                continue
        try:
            page.keyboard.press("End")
        except Exception:
            pass
        try:
            page.evaluate(
                """() => {
                  const sels = [
                    '.bubbles .scrollable-y',
                    '.scrollable-y.scrollable',
                    '.bubbles',
                    '.messages-container',
                    '#column-center .scrollable',
                    '.scrollable-y',
                    '#column-center'
                  ];
                  for (const s of sels) {
                    const el = document.querySelector(s);
                    if (!el) continue;
                    if (el.scrollHeight > el.clientHeight + 10) {
                      el.scrollTop = el.scrollHeight;
                      return true;
                    }
                  }
                  window.scrollTo(0, document.body.scrollHeight);
                  return false;
                }"""
            )
        except Exception:
            pass
        page.wait_for_timeout(700 if clicked else 400)
        at_bottom = False
        try:
            at_bottom = bool(
                page.evaluate(
                    """() => {
                      const sels = [
                        '.bubbles .scrollable-y',
                        '.scrollable-y.scrollable',
                        '.bubbles',
                        '.messages-container'
                      ];
                      for (const s of sels) {
                        const el = document.querySelector(s);
                        if (!el || el.scrollHeight <= el.clientHeight + 10) continue;
                        return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
                      }
                      return false;
                    }"""
                )
            )
        except Exception:
            at_bottom = False
        go_down_visible = False
        for selector in go_down[:5]:
            loc = page.locator(selector)
            try:
                if loc.count() > 0 and loc.first.is_visible(timeout=200):
                    go_down_visible = True
                    break
            except Exception:
                continue
        if at_bottom and not go_down_visible and attempt >= 2:
            break
    print("Jumped to newest messages (bottom of channel)")


LOGIN_HINTS = (
    "log in to telegram by qr",
    "log in by phone number",
    "scan the qr",
    "login code",
)


class TelegramSession:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pw: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> "TelegramSession":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> Page:
        profile = self.settings.chrome_profile_dir
        profile.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self.page

    def close(self) -> None:
        if self.context:
            self.context.close()
        if self._pw:
            self._pw.stop()
        self.context = None
        self._pw = None
        self.page = None

    def _looks_like_login(self, page: Page) -> bool:
        body = (page.inner_text("body") or "").lower()
        return any(hint in body for hint in LOGIN_HINTS)

    def _chat_list_visible(self, page: Page) -> bool:
        if self._looks_like_login(page):
            return False
        locators = [
            page.get_by_text(self.settings.channel_title, exact=False),
            page.get_by_text("Saved Messages", exact=False),
            page.locator(".chat-list .chatlist-chat"),
            page.locator(".chatlist-container .chatlist-chat"),
            page.locator("#column-left .ListItem"),
        ]
        for loc in locators:
            try:
                if loc.count() > 0 and loc.first.is_visible(timeout=800):
                    return True
            except Exception:
                continue
        return False

    def _wait_until_logged_in(self, page: Page, timeout_ms: int = 180_000) -> None:
        if self._chat_list_visible(page) and not self._looks_like_login(page):
            return
        if not self._looks_like_login(page) and self._chat_list_visible(page):
            return
        print(
            "Scan the QR code in the Chromium window.\n"
            "Phone: Telegram → Settings → Devices → Link Desktop Device.\n"
            "Waiting up to 3 minutes..."
        )
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if self._chat_list_visible(page) and not self._looks_like_login(page):
                print("Telegram login detected.")
                return
            page.wait_for_timeout(2000)
        if not self._chat_list_visible(page):
            raise RuntimeError(
                "Still on Telegram login. Scan the QR in the Chromium window and rerun."
            )

    def open_channel(self) -> Page:
        if not self.page or not self.context:
            self.start()
        page = self.page
        assert page is not None

        saved = self.settings.project_root / "data" / "last_opened_url.txt"
        urls = list(self.settings.telegram_start_urls)
        if saved.exists():
            remembered = chat_root_url(saved.read_text(encoding="utf-8"))
            # Chat root only — a message permalink pins mid-history (e.g. 27 Aug).
            if remembered and remembered not in urls:
                urls.insert(0, remembered)

        last_error = "Could not open Telegram Web"
        for url in urls:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            self._wait_until_logged_in(page)
            if self._chat_list_visible(page):
                last_error = ""
                break
        if last_error:
            self._wait_until_logged_in(page)
            if not self._chat_list_visible(page):
                raise RuntimeError(
                    "Still on Telegram login. Scan the QR in the Chromium window and rerun."
                )

        self._click_channel(page)
        page.wait_for_timeout(800)
        jump_to_newest(page)
        current = chat_root_url(page.url) or page.url
        if current.startswith("https://web.telegram.org/"):
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(current, encoding="utf-8")
        return page

    def _header_shows_channel(self, page: Page, title: str) -> bool:
        header = page.locator("header, .chat-info, #MiddleColumn").get_by_text(title, exact=False)
        try:
            return header.first.is_visible(timeout=500)
        except Exception:
            return False

    def _click_sidebar_chat(self, page: Page, title: str) -> bool:
        candidates = page.get_by_text(title, exact=False)
        count = candidates.count()
        for i in range(count):
            el = candidates.nth(i)
            try:
                if not el.is_visible():
                    continue
                box = el.bounding_box()
            except Exception:
                continue
            if box and box["x"] < 480:
                el.click()
                return True
        return False

    def _try_click_title(self, page: Page, title: str) -> bool:
        if self._header_shows_channel(page, title):
            return True
        return self._click_sidebar_chat(page, title)

    def _search_channel(self, page: Page, title: str) -> None:
        search = page.locator(
            'input[type="search"], input[placeholder*="Search" i], '
            ".input-search input, #telegram-search-input"
        )
        if search.count() == 0:
            try:
                page.get_by_role("button", name="Search").first.click(timeout=1500)
                page.wait_for_timeout(400)
            except Exception:
                pass
            search = page.locator("input[type='text'], input[type='search']")
        if search.count() == 0:
            raise RuntimeError(f"Channel not found in sidebar: {title}")
        box = search.first
        box.click()
        box.fill(title)
        page.wait_for_timeout(2000)
        if not self._try_click_title(page, title):
            raise RuntimeError(f"Channel not found in sidebar or search: {title}")

    def _click_channel(self, page: Page) -> None:
        title = self.settings.channel_title
        page.wait_for_timeout(1500)
        # Always hit the sidebar row. Header-already-visible used to skip this
        # and leave Telegram on the last-read message (27 Aug).
        if self._click_sidebar_chat(page, title):
            return
        if self._header_shows_channel(page, title):
            return
        self._search_channel(page, title)
