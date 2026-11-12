from __future__ import annotations

import csv
import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from apply_bot.config import Settings, load_profile


STAFFING_KEYWORDS = [
    "staffing", "consultancy", "recruiting", "recruitment", "talent acquisition",
    "hr consulting", "placement", "headhunter", "staffing firm"
]

STUDENT_KEYWORDS = [
    "student", "intern", "internship", "grad", "graduate", "undergraduate",
    "phd", "master's", "bachelor's", "student at"
]



def company_from_headline(headline: str) -> str:
    """Best-effort company from a LinkedIn headline like 'SDE at Google'."""
    if not headline:
        return ""
    m = re.search(r"\bat\s+(.+?)(?:\s*[|/].*)?$", headline.strip(), flags=re.IGNORECASE)
    if not m:
        return ""
    company = m.group(1).strip(" -|,")
    if len(company) < 2 or len(company) > 80:
        return ""
    return company


def is_recruiter(headline: str) -> bool:
    if not headline:
        return False
    headline_lower = headline.lower()
    return any(kw in headline_lower for kw in STAFFING_KEYWORDS)


def is_student(headline: str) -> bool:
    if not headline:
        return False
    headline_lower = headline.lower()
    return any(kw in headline_lower for kw in STUDENT_KEYWORDS)


def scrape_connections(page: Page, settings: Settings) -> list[dict[str, Any]]:
    contacts = []

    connections_url = "https://www.linkedin.com/mynetwork/invite-connect/connections/"

    print("Waiting for you to log in to LinkedIn and navigate to connections page...")
    print(f"Please go to: {connections_url}")
    print("The browser window should already be open.")

    for i in range(60):
        page.wait_for_timeout(5000)
        if connections_url in page.url and page.locator("a[href*='/in/']").count() > 0:
            print("Detected connections page - proceeding with scraping.")
            break
        print(f"Waiting for login and navigation... ({i+1}/60)")
    else:
        print("Timeout: Could not detect connections page. Proceeding anyway...")

    profile = load_profile()
    current_company = profile.current_company.lower() if profile.current_company else ""

    try:
        page.screenshot(path=str(settings.project_root / "data" / "screenshots" / "linkedin_connections.png"))
        print("Screenshot saved to data/screenshots/linkedin_connections.png")

        unique_urls = set()

        for scroll_i in range(30):
            page.evaluate("""
                () => {
                  const selectors = [
                    '.scaffold-finite-scroll__content',
                    '.mn-connections',
                    'div.scaffold-finite-scroll',
                    'main',
                  ];
                  for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) { el.scrollTop = el.scrollHeight; }
                  }
                  window.scrollTo(0, document.body.scrollHeight);
                }
            """)
            page.wait_for_timeout(2000)

            all_links = page.locator("a[href*='/in/']").all()
            print(f"Scroll {scroll_i + 1}: Found {len(all_links)} profile links")

            for link in all_links:
                try:
                    profile_url = link.get_attribute("href") or ""
                    if not profile_url or "/in/" not in profile_url:
                        continue

                    # Normalize query/fragment so avatar+name links match.
                    profile_url = profile_url.split("?")[0].split("#")[0].rstrip("/")
                    if "/in/" not in profile_url:
                        continue
                    if profile_url in unique_urls:
                        continue

                    name = (link.inner_text(timeout=500) or "").strip()
                    if not name:
                        name = (link.get_attribute("aria-label") or "").strip()
                    if not name:
                        # Skip empty avatar-only anchors; a later named link may claim this URL.
                        continue
                    # Drop "View X's profile" / photo-only labels that aren't a person name card
                    if name.lower().startswith("status is"):
                        continue

                    unique_urls.add(profile_url)

                    # LinkedIn often returns Name + headline in one anchor's inner_text.
                    lines = [ln.strip() for ln in name.replace(chr(13), '').split(chr(10)) if ln.strip()]
                    name = lines[0] if lines else name
                    headline = lines[1] if len(lines) > 1 else ''
                    company = ''

                    try:
                        card_link = page.locator(f"a[href='{profile_url}']").first
                        if card_link.count() > 0:
                            card = card_link.locator("xpath=../../..").first

                            headline_els = card.locator(".mn-connection-card__occupation, .artdeco-entity-lockup__subtitle, .text-body-medium").all()
                            for el in headline_els:
                                try:
                                    h = el.inner_text(timeout=500).strip()
                                    if h:
                                        headline = h
                                        break
                                except Exception:
                                    continue

                            company_els = card.locator(".mn-connection-card__company, .artdeco-entity-lockup__caption").all()
                            for el in company_els:
                                try:
                                    c = el.inner_text(timeout=500).strip()
                                    if c:
                                        company = c
                                        break
                                except Exception:
                                    continue
                    except Exception:
                        pass

                    if is_recruiter(headline) or is_student(headline):
                        pass

                    if current_company and current_company in company.lower():
                        pass

                    if not company:
                        # Prefer headline as company hint; never invent from URL.
                        company = ""

                    print(f"Found contact: {name} at {company} | Headline: {headline[:50] if headline else 'N/A'}")
                    if not company:
                        company = company_from_headline(headline)
                    contacts.append({
                        "name": name,
                        "headline": headline,
                        "company": company,
                        "profile_url": profile_url
                    })
                except Exception as e:
                    print(f"Error processing link: {e}")
                    continue

            if len(all_links) == 0 and scroll_i > 5:
                break

    except Exception as e:
        print(f"Error during scraping: {e}")

    unique_contacts = {}
    for contact in contacts:
        url = contact["profile_url"]
        if url not in unique_contacts:
            unique_contacts[url] = contact

    return list(unique_contacts.values())


def load_existing_contacts(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    profile_urls = set()
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("profile_url"):
                profile_urls.add(row["profile_url"])
    return profile_urls


def save_contacts(contacts: list[dict[str, Any]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    existing_urls = load_existing_contacts(csv_path)

    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        fieldnames = ["name", "headline", "company", "profile_url"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not existing_urls:
            f.seek(0, 2)
            if f.tell() == 0:
                writer.writeheader()

        for contact in contacts:
            if contact["profile_url"] not in existing_urls:
                writer.writerow(contact)
                existing_urls.add(contact["profile_url"])


def load_daily_counts(json_path: Path) -> dict[str, int]:
    if not json_path.exists():
        return {}
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_daily_counts(counts: dict[str, int], json_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(counts, f, indent=2)


def get_today_count(json_path: Path) -> int:
    counts = load_daily_counts(json_path)
    today = datetime.now().strftime("%Y-%m-%d")
    return counts.get(today, 0)


def increment_today_count(json_path: Path) -> int:
    counts = load_daily_counts(json_path)
    today = datetime.now().strftime("%Y-%m-%d")
    counts[today] = counts.get(today, 0) + 1
    save_daily_counts(counts, json_path)
    return counts[today]


def has_recent_chat(profile_url: str, page: Page) -> bool:
    try:
        page.goto(f"{profile_url}detail/contact-info/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        conversation = page.locator(f"[data-urn*='{profile_url.split('/in/')[-1].split('/')[0]}']").first
        if conversation.count() > 0:
            timestamp_el = conversation.locator(".msg-s-message-list__time, .message-list-item__timestamp").first
            if timestamp_el.count() > 0:
                timestamp_text = timestamp_el.inner_text(timeout=500)
                if "day" in timestamp_text.lower() or "hour" in timestamp_text.lower() or "min" in timestamp_text.lower():
                    return True
    except Exception:
        pass
    return False
