# Apply bot (Telegram referrals → email + Google Forms)

A local helper your friends can clone and run for themselves. It watches a Telegram referral channel (default: **SDE Premium Group**), extracts posts, keeps openings that match **your** profile, then:

- writes and **auto-sends** Gmail to company-domain emails
- fills and **submits** Google Forms from your profile
- logs everything to `data/job_tracker.xlsx`

Each person uses **their own** `config/profile.yaml`, Gmail, Telegram login, and resume. Nothing personal is required in the repo.

## What you need

- Python 3.11+
- A Telegram account that can open the channel
- Gmail in the **same** Chromium profile the bot uses
- Your resume PDF (and optionally a Google Drive link set to “anyone with the link”)

## Setup

```bash
git clone <this-repo-url>
cd apply-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/pw-browsers" playwright install chromium
cp .env.example .env
cp config/profile.example.yaml config/profile.yaml
```

Edit `config/profile.yaml`:

- name, email, phone, college, batch / graduation year
- `resume_path` (absolute path to your PDF)
- LinkedIn, GitHub, portfolio, Drive resume link
- `skills` and `proof_points` (real projects with numbers)

Edit `.env` only if your channel title is not `SDE Premium Group`:

```bash
TELEGRAM_CHANNEL_TITLE=SDE Premium Group
```

Optional: tune `config/settings.yaml` (allow/deny titles, auto-send). Defaults are intern / SDE / fullstack / frontend / backend / GenAI-app / DevOps intern.

## First login (once)

```bash
source .venv/bin/activate
export PLAYWRIGHT_BROWSERS_PATH="$PWD/data/pw-browsers"
PYTHONPATH=src python -m apply_bot open-channel
```

Chromium opens [web.telegram.org](https://web.telegram.org). Scan the QR **in that window** (not your daily Chrome). Then open Gmail in the **same** window and stay signed in.

The bot profile lives in `data/chrome-profile` (gitignored).

## Daily use

```bash
source .venv/bin/activate
export PLAYWRIGHT_BROWSERS_PATH="$PWD/data/pw-browsers"
PYTHONPATH=src python -m apply_bot apply-once --limit 80
```

Or leave it polling:

```bash
PYTHONPATH=src python -m apply_bot watch
```

| Command | What it does |
|---|---|
| `apply-once --limit 80` | Newest posts first, apply matches, retry incomplete forms |
| `dry-run --limit 20` | Score posts only, no mail/forms |
| `watch` | Repeat every 90s |
| `list` / `list --applied` | Print the tracker |

Tracker files (local only): `data/job_tracker.xlsx`, `data/job_tracker.csv`, `data/applications.db`.

## What the bot will and will not do

- Fills name, email, phone, college, dates, resume link, and common Yes/No from **your** profile
- Sends mail only to **company-domain** addresses; personal Gmail/yahoo stay Draft
- Marks a Google Form submitted only when the page says the response was recorded
- Skips login walls (Internshala, Workday, Greenhouse, etc.) unless you log in yourself in the bot Chromium
- Does **not** invent skills, board marks, or videos

If a required field has no honest answer, the run prints `ASK (...)`.

## Share this with friends

1. Push this repo (without `config/profile.yaml` or `.env`).
2. Each friend clones, copies the example profile, fills **their** details, logs into Telegram + Gmail once.
3. Never share `data/chrome-profile`, `.env`, or your filled `profile.yaml`.

## Tests

```bash
PYTHONPATH=src pytest
```

You need a filled `config/profile.yaml` for tests that load the real profile.

## Safety

This applies **as you**. Review auto-sent mail in Gmail Sent. Keep the channel you watch one you are allowed to use. Do not commit API keys or resumes.
