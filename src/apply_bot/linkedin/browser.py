from __future__ import annotations

import time

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from apply_bot.config import Settings


class LinkedInSession:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pw: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> "LinkedInSession":
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

    def open_connections(self) -> Page:
        if not self.page or not self.context:
            self.start()
        page = self.page
        assert page is not None

        page.goto("https://www.linkedin.com/mynetwork/invite-connect/connections/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        return page

    def open_inbox(self) -> Page:
        if not self.page or not self.context:
            self.start()
        page = self.page
        assert page is not None

        page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        return page
