# Job Application & LinkedIn Referral Automation

An end-to-end autonomous assistant to streamline job applications, candidate outreach, and referral networking across Telegram, LinkedIn, Gmail, Google Forms, and direct ATS platforms.

---

## 🌟 Key Features

### 1. LinkedIn Referral Outreach & Messenger
- **Automated 1st-Degree Connection Scraping:** Extracts names, profile links, job titles, and current companies from your network.
- **Contextual Referral Messaging:** Automatically crafts and sends personalized referral requests with your resume PDF attached directly in LinkedIn chat.
- **Human-like Cadence & Rate Limiting:** Enforces safe delays (~30s jitter between messages) and daily caps to keep your LinkedIn account safe and avoid bot detection.
- **Inbox Follow-up & Response Classification:**
  - Scans conversation threads for inbound replies.
  - Automatically classifies responses into categories (e.g. *asked for resume*, *asked for job ID / link*, *referred*, *no openings*).
  - Matches candidate target companies against configured open positions (`data/followup_jobs.json`) to supply exact job IDs, links, and customized follow-up notes.

### 2. Telegram Referral Scanner & Auto-Applier
- Monitors Telegram referral channels (e.g., SDE Premium channels) looking back up to 14 days.
- Extracts company names, job titles, eligibility criteria, and links.
- Intelligently filters openings matching your experience level (0-2 years, freshers) and tech stack.

### 3. Automated Gmail & Google Forms Submissions
- **Company-Domain Gmail Dispatch:** Generates professional outreach emails tailored to hiring teams with your verified resume attached.
- **Google Form Filler:** Seamlessly fills out complex Google Form questionnaires (personal info, education, CGPA, graduation batch, project metrics, and PDF upload).
- **Audit Screenshots:** Captures full-page screenshots before and after form submission for complete auditability.

### 4. Direct ATS Application Support
- Automates direct job portal applications across modern ATS systems (AshbyHQ, Greenhouse, Lever, Workable).
- Auto-populates personal background, notice period, location preferences, and uploads resume files with human verification safeguards.

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.11+
- Windows PowerShell or Unix Shell
- Google Chrome / Chromium
- A PDF Resume (placed in `data/resume.pdf` or referenced in `config/profile.yaml`)

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd apply-automation-main
   ```

2. **Set up virtual environment:**
   ```bash
   # Windows PowerShell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies & Playwright Chromium:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Initialize configuration files:**
   ```bash
   cp .env.example .env
   cp config/profile.example.yaml config/profile.yaml
   cp data/followup_jobs.example.json data/followup_jobs.json
   ```

5. **Customize your profile:**
   Edit `config/profile.yaml` with your genuine personal details:
   - Full name, email, phone, location preferences, notice period.
   - Education, CGPA, graduation batch.
   - Verified technical skills, project proof points, and path to your resume PDF.

---

## 💻 CLI Usage

All core workflows can be run using the provided PowerShell helper `run.ps1` or directly via Python module `apply_bot.cli`.

### LinkedIn Automation

| Task | Command | Description |
|---|---|---|
| **Login Session** | `.\run.ps1 linkedin-login` | Launches Chromium to log into LinkedIn and persist your local session. |
| **Scrape Connections** | `.\run.ps1 linkedin-scrape` | Scrapes 1st-degree connections into a local contact CSV. |
| **Referral Outreach** | `.\run.ps1 linkedin-dm` | Sends polite referral messages + attached resume PDF with safety delays. |
| **Inbox Scanner** | `.\run.ps1 linkedin-inbox` | Quick scan of inbound replies looking for resume requests. |
| **Follow-up Engine** | `.\run.ps1 linkedin-followup` | Categorizes replies and sends role links/IDs to connections who offered help. |

### Telegram & Job Application Engine

| Task | Command | Description |
|---|---|---|
| **Telegram Channel Login** | `.\run.ps1 open-channel` | Opens Telegram Web for one-time QR login. |
| **Dry Run Evaluation** | `python -m apply_bot dry-run --limit 20` | Evaluates latest posts without sending emails or submitting forms. |
| **Apply Once** | `python -m apply_bot apply-once --limit 80` | Evaluates and applies to matching openings. |
| **Continuous Watcher** | `python -m apply_bot watch` | Runs recurring check loop every 90 seconds. |
| **Tracker Summary** | `python -m apply_bot list` | Displays real-time status of applications and leads. |

---

## 🔒 Security & Privacy Best Practices

- **Zero Credential Leaks:** No personal credentials, session tokens, or personal resumes are tracked by version control.
- **Gitignored Runtime Data:** `data/chrome-profile/`, `.env`, `config/profile.yaml`, `data/*.db`, and all generated spreadsheets/CSVs are strictly ignored in `.gitignore`.
- **Anti-Spam Throttling:** Built-in rate limits prevent aggressive messaging and protect your social profiles from platform restrictions.
- **Never commit `config/profile.yaml` or `.env`:** Always use the `.example` templates when sharing code or committing changes.

---

## 🧪 Testing

Run pytest test suite:
```bash
pytest tests/
```

---

## 📄 License
This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
