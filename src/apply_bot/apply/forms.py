from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page

from apply_bot.apply.form_fill import (
    _heading_core,
    fact_bank,
    heading_score,
    is_askable_question,
    is_person_name_question,
    map_questions_with_gemini,
    merge_answers,
    stack_option_ticks,
)
from apply_bot.config import Profile, Settings, load_settings
from apply_bot.models import ApplicationDraft, JobPost

SUBMIT_BUTTON_PATTERNS = [r"^Submit$", r"^Send$", r"^Submit form$", r"^Send form$"]
NEXT_BUTTON_PATTERNS = [r"^Next$", r"^Continue$"]
CAREERS_CLICK_PATTERNS = [
    r"^Submit application$",
    r"^Submit$",
    r"^Apply now$",
    r"^Apply$",
    r"^Send application$",
]
CAREERS_THANKS = (
    "thank you",
    "thanks for applying",
    "application has been received",
    "application received",
    "application submitted",
    "successfully submitted",
    "we have received your application",
)


@dataclass
class FormAttempt:
    submitted: bool
    fail_reason: str = ""
    screenshot_path: str | None = None


def response_recorded(body: str) -> bool:
    text = (body or "").lower()
    return (
        "your response has been recorded" in text
        or "response has been recorded" in text
        or "already responded" in text
        or "you filled out this form" in text
    )


def ats_kind(url: str | None) -> str:
    lowered = (url or "").lower()
    if "docs.google.com/forms" in lowered or "forms.gle" in lowered:
        return "google_form"
    if "rippling.com" in lowered:
        return "rippling"
    if "myworkdayjobs.com" in lowered or "workday.com" in lowered:
        return "workday"
    if "internshala.com" in lowered:
        return "internshala"
    if "wellfound.com" in lowered:
        return "wellfound"
    return "other"


def _looks_like_login(body: str) -> bool:
    text = (body or "").lower()
    if not any(w in text for w in ("sign in", "log in", "login", "sso")):
        return False
    return any(w in text for w in ("password", "email", "continue with", "sso", "otp"))


def _fill_common_ats_fields(page: Page, profile: Profile) -> None:
    pairs = (
        (("name", "full name", "first name"), profile.full_name),
        (("email", "e-mail"), profile.email),
        (("phone", "mobile", "tel"), profile.phone),
        (("linkedin",), profile.linkedin),
    )
    for keys, value in pairs:
        if not value:
            continue
        for key in keys:
            loc = page.locator(
                f"input[name*='{key}' i], input[id*='{key}' i], "
                f"input[placeholder*='{key}' i], input[aria-label*='{key}' i]"
            )
            try:
                if loc.count():
                    loc.first.fill(value)
                    break
            except Exception:
                continue
    _attach_resume(page, profile)


def careers_confirmed(body: str) -> bool:
    text = (body or "").lower()
    return any(phrase in text for phrase in CAREERS_THANKS)


def required_fail_reason(body: str, titles: list[str] | None = None) -> str:
    text = body or ""
    lowered = text.lower()
    if "no longer accepting responses" in lowered or "form is closed" in lowered:
        return "form_closed"
    if "no longer available" in lowered and "job" in lowered:
        return "job_closed"
    if "sign in" in lowered and "google" in lowered:
        return "needs_login"
    if "this is a required question" in lowered or "required question" in lowered:
        hits = [t for t in (titles or []) if t and t.lower() in lowered]
        if hits:
            return "missing: " + ", ".join(hits[:4])
        return "missing: required question"
    if "aria-invalid" in lowered:
        return "missing: invalid field"
    return "submit_not_confirmed"


def _click_button(page: Page, names: list[str]) -> bool:
    for name in names:
        loc = page.get_by_role("button", name=re.compile(name, re.I))
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                return True
        except Exception:
            continue
    return False


def extract_questions(page: Page) -> list[dict]:
    try:
        data = page.evaluate(
            """() => {
              const blocks = [
                ...document.querySelectorAll('[role="listitem"], .Qr7Oae, .freebirdFormviewerViewItemsItemItem')
              ];
              return blocks.map((el) => {
                const titleEl = el.querySelector('[role="heading"], .M7eMe, label, legend');
                const raw = (titleEl?.innerText || el.getAttribute('aria-label') || '').trim();
                const title = raw.split('\\n')[0].trim();
                const options = [...el.querySelectorAll(
                  '[role="radio"], [role="checkbox"], [role="option"], option, .docssharedWizToggleLabeledLabelText'
                )]
                  .map((o) => (o.innerText || o.getAttribute('aria-label') || '').trim())
                  .filter((t) => t && t.length < 120);
                return { title, options: [...new Set(options)] };
              }).filter((q) => q.title && q.title.length > 1);
            }"""
        )
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    labels = []
    for loc in page.locator("label, [role='heading']").all():
        try:
            text = (loc.inner_text(timeout=300) or "").strip()
        except Exception:
            continue
        if text:
            labels.append({"title": text, "options": []})
    return labels


def collect_required_titles(page: Page) -> list[str]:
    try:
        data = page.evaluate(
            """() => {
              const out = [];
              document.querySelectorAll('[role="listitem"], .Qr7Oae').forEach((el) => {
                const text = (el.innerText || '').toLowerCase();
                const bad = el.querySelector('[aria-invalid="true"]')
                  || text.includes('this is a required question')
                  || text.includes('required question');
                if (!bad) return;
                const title = el.querySelector('[role="heading"], .M7eMe, label, legend');
                const name = (title?.innerText || '').trim();
                if (name) out.push(name.split('\\n')[0]);
              });
              return out;
            }"""
        )
        if isinstance(data, list):
            return [str(x) for x in data if x]
    except Exception:
        pass
    return []


_JS_FILL = """([question, answer]) => {
  const clean = (s) => (s || '').replace(/[\\s\\u00a0*：:]+/g, ' ').trim().toLowerCase()
    .replace(/\\s*\\([^)]*\\)\\s*/g, ' ').replace(/\\[[^\\]]*\\]/g, ' ')
    .replace(/\\s+/g, ' ').replace(/^[.\\s?-]+|[.\\s?-]+$/g, '');
  const q = clean(question);
  if (!q || !answer) return false;
  const shortId = new Set(['name', 'email', 'city', 'phone', 'state']);
  const headingOf = (el) => {
    const heading = el.querySelector('[role="heading"], .M7eMe, legend');
    const raw = heading ? heading.innerText : '';
    return clean((raw || '').split('\\n')[0]);
  };
  const score = (h) => {
    if (!h) return 0;
    if (h === q) return 100;
    const [shorter, longer] = h.length <= q.length ? [h, q] : [q, h];
    if (shortId.has(shorter) && longer !== shorter) {
      if (longer.startsWith(shorter + ' ') && longer.length < 22) return 85;
      return 0;
    }
    if (h.startsWith(q) || q.startsWith(h)) return Math.min(h.length, q.length) >= 8 ? 80 : 0;
    if (q.length >= 12 && h.includes(q)) return 55;
    if (h.length >= 12 && q.includes(h)) return 45;
    return 0;
  };
  const blocks = [...document.querySelectorAll('[role="listitem"], .Qr7Oae')];
  let block = null;
  let best = 0;
  for (const el of blocks) {
    const s = score(headingOf(el));
    if (s > best) { best = s; block = el; }
  }
  if (!block || best < 45) return false;
  const wanted = clean(answer);
  const radios = [...block.querySelectorAll('[role="radio"]')];
  for (const radio of radios) {
    const row = radio.closest('.nWQGrd, .docssharedWizToggleLabeledRoot, label') || radio.parentElement;
    const lab = row ? row.querySelector('.docssharedWizToggleLabeledLabelText, .aDTYNe') : null;
    const text = clean(radio.getAttribute('aria-label') || '')
      || clean(lab && lab.innerText)
      || clean(row && row.innerText);
    const norm = (s) => clean(s).replace(/:$/,'');
    const have = norm(text);
    const need = norm(wanted);
    if (!have || have.length < 2) continue;
    if (have === need || have.startsWith(need) || need.startsWith(have)) {
      radio.click();
      return 'radio';
    }
  }
  const inputs = [...block.querySelectorAll(
    "input[type='text'], input[type='email'], input[type='tel'], textarea"
  )];
  if (inputs.length) {
    const input = inputs[0];
    input.focus();
    input.value = answer;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return 'text';
  }
  return false;
}"""


_JS_BEST_BLOCK = """(question) => {
  const clean = (s) => (s || '').replace(/[\\s\\u00a0*：:]+/g, ' ').trim().toLowerCase()
    .replace(/\\s*\\([^)]*\\)\\s*/g, ' ').replace(/\\[[^\\]]*\\]/g, ' ')
    .replace(/\\s+/g, ' ').replace(/^[.\\s?-]+|[.\\s?-]+$/g, '');
  const q = clean(question);
  const shortId = new Set(['name', 'email', 'city', 'phone', 'state']);
  const headingOf = (el) => {
    const heading = el.querySelector('[role="heading"], .M7eMe, legend');
    const raw = heading ? heading.innerText : '';
    return clean((raw || '').split('\\n')[0]);
  };
  const score = (h) => {
    if (!h) return 0;
    if (h === q) return 100;
    const [shorter, longer] = h.length <= q.length ? [h, q] : [q, h];
    if (shortId.has(shorter) && longer !== shorter) {
      if (longer.startsWith(shorter + ' ') && longer.length < 22) return 85;
      return 0;
    }
    if (h.startsWith(q) || q.startsWith(h)) return Math.min(h.length, q.length) >= 8 ? 80 : 0;
    if (q.length >= 12 && h.includes(q)) return 55;
    if (h.length >= 12 && q.includes(h)) return 45;
    return 0;
  };
  const blocks = [...document.querySelectorAll('[role="listitem"], .Qr7Oae')];
  let idx = -1;
  let best = 0;
  blocks.forEach((el, i) => {
    const s = score(headingOf(el));
    if (s > best) { best = s; idx = i; }
  });
  return best >= 45 ? idx : -1;
}"""


def _is_identity_question(question: str) -> bool:
    if is_person_name_question(question):
        return True
    return _heading_core(question) in {
        "name",
        "full name",
        "email",
        "e-mail",
        "phone",
        "mobile",
        "city",
        "college",
        "current company",
    }


def _question_block(page: Page, question: str):
    try:
        idx = page.evaluate(_JS_BEST_BLOCK, question)
        if isinstance(idx, int) and idx >= 0:
            return page.locator('[role="listitem"], .Qr7Oae').nth(idx)
    except Exception:
        pass
    blocks = page.locator('[role="listitem"], .Qr7Oae')
    try:
        total = blocks.count()
    except Exception:
        return None
    best_i = -1
    best_s = 0
    for i in range(total):
        try:
            heading = blocks.nth(i).locator('[role="heading"], .M7eMe, legend').first
            text = heading.inner_text(timeout=300) if heading.count() else ""
        except Exception:
            text = ""
        score = heading_score(question, text)
        if score > best_s:
            best_s = score
            best_i = i
    if best_i >= 0 and best_s >= 45:
        return blocks.nth(best_i)
    return None


def _js_fill(page: Page, question: str, answer: str) -> bool:
    if not question or not answer:
        return False
    try:
        return bool(page.evaluate(_JS_FILL, [question, answer]))
    except Exception:
        return False


def _fill_text_like(page: Page, question: str, answer: str) -> bool:
    if not answer:
        return False
    block = _question_block(page, question)
    if block is not None:
        target = block.locator("input[type='text'], input[type='email'], input[type='tel'], textarea")
        try:
            if target.count():
                target.first.fill(answer)
                return True
        except Exception:
            pass
    return False


def _select_option(page: Page, question: str, answer: str, options: list[str]) -> bool:
    if not answer:
        return False
    wanted = answer.strip().lower()
    pick = next((opt for opt in options if opt.strip().lower() == wanted), None)
    if not pick:
        pick = next((opt for opt in options if wanted in opt.lower() or opt.lower() in wanted), None)
    if not pick and options:
        if wanted in {"yes", "y"}:
            pick = next((opt for opt in options if opt.lower().startswith("yes")), None)
        if wanted in {"no", "n"}:
            pick = next((opt for opt in options if opt.lower().startswith("no")), None)
        if "immediate" in wanted:
            pick = next((opt for opt in options if "immediate" in opt.lower()), None)
    if not pick:
        pick = answer
    block = _question_block(page, question)
    if block is None and not _is_identity_question(question):
        block = page.locator('[role="listitem"], .Qr7Oae').filter(has_text=question[:48]).first
    if block is None:
        return False
    try:
        choice = block.get_by_text(pick, exact=True).first
        if choice.count():
            choice.click()
            return True
    except Exception:
        pass
    if _fill_dropdown(page, question, pick):
        return True
    try:
        page.get_by_text(pick, exact=True).first.click(timeout=1500)
        return True
    except Exception:
        return False


def _fill_dropdown(page: Page, question: str, answer: str) -> bool:
    if not answer:
        return False
    snippet = re.sub(r"[\s\xa0*]+", " ", question or "").strip()[:40]
    located = _question_block(page, question)
    if located is not None:
        block = located
    elif _is_identity_question(question):
        return False
    else:
        block = page.locator('[role="listitem"], .Qr7Oae').filter(
            has_text=snippet or question[:24]
        )
    try:
        box = block.locator('[role="listbox"], .MocG8c, .ry3kXd')
        choose = block.get_by_text(re.compile(r"^Choose$", re.I))
        if box.count():
            box.first.click()
        elif choose.count():
            choose.first.click()
        else:
            heading = page.get_by_role("heading", name=re.compile(re.escape(snippet[:20] or answer), re.I))
            if heading.count():
                parent = heading.first.locator("xpath=ancestor::*[@role='listitem' or contains(@class,'Qr7Oae')][1]")
                opener = parent.locator('[role="listbox"], .MocG8c')
                if opener.count():
                    opener.first.click()
                else:
                    return False
            else:
                return False
        page.wait_for_timeout(450)
        opt = page.locator('[role="option"]').filter(has_text=re.compile(rf"^{re.escape(answer)}$", re.I))
        if not opt.count():
            opt = page.locator('[role="option"]').filter(has_text=re.compile(re.escape(answer), re.I))
        if opt.count():
            opt.first.click()
            return True
        page.keyboard.type(answer, delay=40)
        page.keyboard.press("Enter")
        return True
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
    return False


def _tick_stack_if_tech(page: Page, question: str, options: list[str]) -> bool:
    q = (question or "").lower()
    if not any(w in q for w in ("technolog", "stack", "shipped", "tools do you", "which tools", "which of these")):
        return False
    ticks = stack_option_ticks(options)
    if len(ticks) < 2 and "spring" not in q:
        return False
    ok = False
    for opt in ticks:
        if _select_option(page, question, opt, [opt]):
            ok = True
    return ok


def _fill_mapped(page: Page, questions: list[dict], answers: dict[str, str], extra: dict[str, str] | None = None) -> None:
    extra = extra or {}
    for item in questions:
        title = item.get("title") or ""
        answer = answers.get(title) or ""
        options = item.get("options") or []
        if not answer:
            continue
        if _js_fill(page, title, answer):
            if answer.strip().lower().startswith("other") and extra.get("other_stack"):
                _fill_text_like(page, title, extra["other_stack"])
            continue
        if answer.strip().lower().startswith("other"):
            block = _question_block(page, title)
            if block is None:
                block = page.locator('[role="listitem"], .Qr7Oae').filter(has_text=title[:48])
            try:
                other = block.get_by_text(re.compile(r"^Other", re.I)).first
                if other.count():
                    other.click()
                    if extra.get("other_stack"):
                        _fill_text_like(page, title, extra["other_stack"])
                    continue
            except Exception:
                pass
        if options and _tick_stack_if_tech(page, title, options):
            continue
        if options and _select_option(page, title, answer, options):
            continue
        if _fill_dropdown(page, title, answer):
            continue
        _fill_text_like(page, title, answer)


def _attach_resume(page: Page, profile: Profile) -> bool:
    resume = Path(profile.resume_path).expanduser() if profile.resume_path else None
    if not resume or not resume.exists():
        print(f"Resume attach skipped: file missing ({profile.resume_path})")
        return False
    attached = False
    file_inputs = page.locator('input[type="file"]')
    try:
        for i in range(min(file_inputs.count(), 3)):
            file_inputs.nth(i).set_input_files(str(resume))
            attached = True
    except Exception as exc:
        print(f"Resume attach via input failed: {exc}")
    if attached:
        return True
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    add_btns = _resume_add_file_buttons(page)
    for i in range(min(len(add_btns), 2)):
        btn = add_btns[i]
        try:
            with page.expect_file_chooser(timeout=1500) as chooser:
                btn.click(timeout=2000, force=True)
            chooser.value.set_files(str(resume))
            attached = True
            continue
        except Exception:
            pass
        if page.locator('iframe[src*="picker"]').count():
            if _attach_from_drive_picker(page, resume):
                attached = True
                continue
        try:
            btn.click(timeout=2000, force=True)
            page.wait_for_timeout(600)
        except Exception as exc:
            print(f"Resume Add file picker failed: {exc}")
        if _attach_from_drive_picker(page, resume):
            attached = True
    if not attached:
        print("Resume attach skipped: no file input on page")
    return attached


def _resume_add_file_buttons(page: Page) -> list:
    buttons = []
    blocks = page.locator('[role="listitem"], .Qr7Oae')
    try:
        total = blocks.count()
    except Exception:
        return buttons
    for i in range(total):
        block = blocks.nth(i)
        try:
            text = (block.inner_text(timeout=400) or "").lower()
        except Exception:
            continue
        if "video" in text:
            continue
        if not any(w in text for w in ("resume", "cv", "pdf only", "upload your")):
            continue
        loc = block.get_by_role("button", name=re.compile(r"add file|browse|choose file", re.I))
        if not loc.count():
            loc = block.get_by_text(re.compile(r"^Add file$", re.I))
        if loc.count():
            buttons.append(loc.first)
    return buttons


def _attach_from_drive_picker(page: Page, resume: Path) -> bool:
    try:
        picker = page.locator('iframe[src*="picker"]')
        if picker.count():
            frame = page.frame_locator('iframe[src*="picker"]').last
            try:
                tab = frame.get_by_role("tab", name=re.compile(r"upload", re.I))
                if not tab.count():
                    tab = frame.get_by_text(re.compile(r"^Upload$", re.I))
                if tab.count():
                    tab.first.click(timeout=1500)
                    page.wait_for_timeout(400)
            except Exception:
                pass
            hidden = frame.locator('input[type="file"]')
            if hidden.count():
                hidden.first.set_input_files(str(resume))
                return True
            with page.expect_file_chooser(timeout=3500) as chooser:
                frame.get_by_role("button", name=re.compile(r"^Browse$", re.I)).click()
            chooser.value.set_files(str(resume))
            return True
    except Exception:
        pass
    scopes = [page, *page.frames]
    for scope in scopes:
        try:
            tab = scope.get_by_role("tab", name=re.compile(r"upload", re.I))
            if tab.count():
                tab.first.click()
                page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            browse = scope.get_by_role("button", name=re.compile(r"^Browse$", re.I))
            if not browse.count():
                browse = scope.get_by_text(re.compile(r"^Browse$", re.I))
            if not browse.count():
                continue
            with page.expect_file_chooser(timeout=3000) as chooser:
                browse.first.click()
            chooser.value.set_files(str(resume))
            return True
        except Exception:
            continue
    return False


def _save_fail_shot(page: Page, settings: Settings, fingerprint: str) -> str | None:
    dest = settings.screenshot_dir / f"form-fail-{fingerprint or 'unknown'}.png"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(dest), full_page=True)
        return str(dest)
    except Exception as exc:
        print(f"Form fail screenshot failed: {exc}")
        return None


def _check_record_email(page: Page) -> None:
    try:
        box = page.get_by_role(
            "checkbox",
            name=re.compile(r"record .+ as the email to be included", re.I),
        )
        if box.count():
            if box.first.get_attribute("aria-checked") != "true":
                box.first.click()
            return
    except Exception:
        pass
    try:
        page.get_by_text(re.compile(r"Record .+ as the email to be included", re.I)).first.click(timeout=1200)
    except Exception:
        pass


def submit_google_form(page: Page) -> bool:
    for _ in range(8):
        page.wait_for_timeout(700)
        body = page.inner_text("body") or ""
        if response_recorded(body):
            return True
        if _click_button(page, SUBMIT_BUTTON_PATTERNS):
            page.wait_for_timeout(1400)
            if response_recorded(page.inner_text("body") or ""):
                return True
            continue
        if _click_button(page, NEXT_BUTTON_PATTERNS):
            continue
        break
    return response_recorded(page.inner_text("body") or "")


def _complete_page(
    page: Page,
    post: JobPost,
    draft: ApplicationDraft,
    profile: Profile,
    settings: Settings,
) -> None:
    _check_record_email(page)
    facts = fact_bank(profile, post, draft)
    questions = extract_questions(page)
    gemini = map_questions_with_gemini(questions, facts, settings)
    answers = merge_answers(questions, facts, gemini)
    _fill_mapped(page, questions, answers, extra=facts)
    _attach_resume(page, profile)
    unanswered = [
        (item.get("title") or "").strip()
        for item in questions
        if is_askable_question(item.get("title") or "")
        and not (answers.get(item.get("title") or "") or "").strip()
    ]
    if unanswered:
        print("    ASK (new fields I cannot answer): " + " | ".join(unanswered[:8]))


def _fail_attempt(page: Page, settings: Settings, post: JobPost) -> FormAttempt:
    titles = collect_required_titles(page)
    body = ""
    try:
        body = page.inner_text("body") or ""
    except Exception:
        pass
    reason = required_fail_reason(body, titles)
    shot = _save_fail_shot(page, settings, post.source_fingerprint)
    print(f"    form fail: {reason}" + (f" shot={shot}" if shot else ""))
    return FormAttempt(False, fail_reason=reason, screenshot_path=shot)


def prepare_form(
    page: Page,
    post: JobPost,
    draft: ApplicationDraft,
    profile: Profile,
    submit: bool = False,
    settings: Settings | None = None,
) -> FormAttempt:
    if not post.apply_url:
        raise RuntimeError("No form URL")
    settings = settings or load_settings()
    page.goto(post.apply_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    if not submit:
        _complete_page(page, post, draft, profile, settings)
        return FormAttempt(False, fail_reason="submit_disabled")
    for _ in range(6):
        _complete_page(page, post, draft, profile, settings)
        if submit_google_form(page):
            return FormAttempt(True)
        if _click_button(page, NEXT_BUTTON_PATTERNS):
            page.wait_for_timeout(800)
            continue
        break
    if submit_google_form(page):
        return FormAttempt(True)
    return _fail_attempt(page, settings, post)


def try_submit_careers(
    page: Page,
    post: JobPost,
    draft: ApplicationDraft,
    profile: Profile,
    submit: bool = False,
    settings: Settings | None = None,
) -> FormAttempt:
    if not post.apply_url:
        raise RuntimeError("No careers URL")
    settings = settings or load_settings()
    page.goto(post.apply_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    kind = ats_kind(post.apply_url)
    body = page.inner_text("body") or ""
    if _looks_like_login(body):
        shot = _save_fail_shot(page, settings, post.source_fingerprint)
        print(f"    careers fail: needs_login ({kind}) shot={shot}")
        return FormAttempt(False, fail_reason="needs_login", screenshot_path=shot)
    if kind in {"rippling", "workday", "internshala", "wellfound", "other"}:
        _fill_common_ats_fields(page, profile)
    _complete_page(page, post, draft, profile, settings)
    if not submit:
        return FormAttempt(False, fail_reason="submit_disabled")
    _click_button(page, CAREERS_CLICK_PATTERNS)
    page.wait_for_timeout(1500)
    done = page.inner_text("body") or ""
    if careers_confirmed(done):
        return FormAttempt(True)
    shot = _save_fail_shot(page, settings, post.source_fingerprint)
    lowered = done.lower()
    if "no longer available" in lowered or "no longer accepting" in lowered:
        reason = "job_closed"
    elif "log in" in lowered or "sign in" in lowered:
        reason = "needs_login"
    else:
        reason = "extra_step"
    print(f"    careers fail: {reason}" + (f" shot={shot}" if shot else ""))
    return FormAttempt(False, fail_reason=reason, screenshot_path=shot)
