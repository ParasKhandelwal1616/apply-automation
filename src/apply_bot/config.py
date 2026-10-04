from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


def find_project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "config" / "settings.yaml").exists():
            return parent
    return Path.cwd()


class Settings(BaseModel):
    channel_title: str = "SDE Premium Group"
    poll_interval_seconds: int = 90
    dry_run_default: bool = True
    extract_limit: int = 10
    min_text_chars: int = 80
    screenshot_dir: Path = Path("data/screenshots")
    database_path: Path = Path("data/applications.db")
    chrome_profile_dir: Path = Path("data/chrome-profile")
    telegram_start_urls: list[str] = Field(
        default_factory=lambda: [
            "https://web.telegram.org/k/",
            "https://web.telegram.org/a/",
        ]
    )
    allow_titles: list[str] = Field(default_factory=list)
    deny_titles: list[str] = Field(default_factory=list)
    profile_stack_signals: list[str] = Field(default_factory=list)
    ai_engineer_app_signals: list[str] = Field(default_factory=list)
    personal_email_domains: list[str] = Field(default_factory=list)
    famous_brands: list[str] = Field(default_factory=list)
    careers_url_markers: list[str] = Field(default_factory=list)
    auto_send_email: bool = True
    auto_submit_forms: bool = True
    auto_submit_careers: bool = True
    use_gemini: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    project_root: Path = Field(default_factory=find_project_root)

    def resolve(self) -> "Settings":
        root = self.project_root
        self.screenshot_dir = (root / self.screenshot_dir).resolve()
        self.database_path = (root / self.database_path).resolve()
        env_profile = os.environ.get("BROWSER_USER_DATA_DIR", "").strip()
        if env_profile:
            self.chrome_profile_dir = Path(env_profile).expanduser().resolve()
        else:
            self.chrome_profile_dir = (root / self.chrome_profile_dir).resolve()
        env_title = os.environ.get("TELEGRAM_CHANNEL_TITLE", "").strip()
        if env_title:
            self.channel_title = env_title
        self.gemini_model = os.environ.get("GEMINI_MODEL", self.gemini_model).strip()
        if self.use_gemini:
            self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        else:
            self.gemini_api_key = ""
        return self


class Profile(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    batch: str = "2027"
    college: str = ""
    resume_path: str = ""
    resume_drive: str = ""
    portfolio: str = ""
    linkedin: str = ""
    github: str = ""
    skills: list[str] = Field(default_factory=list)
    proof_points: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    notes: str = ""
    city: str = ""
    state: str = ""
    country: str = "India"
    degree: str = ""
    branch: str = ""
    cgpa: str = ""
    graduation_year: str = ""
    current_company: str = ""
    current_role: str = ""
    available: str = "Immediate"
    notice_period: str = "Immediate"
    experience_years: str = ""
    languages: str = "English, Hindi"
    gender: str = ""
    tenth: str = ""
    twelfth: str = ""
    current_ctc: str = ""
    current_stipend: str = ""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def load_settings() -> Settings:
    root = find_project_root()
    load_dotenv(root / ".env")
    browsers = root / "data" / "pw-browsers"
    browsers.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
    raw = _load_yaml(root / "config" / "settings.yaml")
    settings = Settings.model_validate({**raw, "project_root": root})
    return settings.resolve()


def ensure_resume_copy(profile: Profile, dest_dir: Path) -> Profile:
    src = Path(profile.resume_path).expanduser() if profile.resume_path else None
    if not src or not src.exists():
        return profile
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "resume.pdf"
    if src.resolve() != dest.resolve():
        dest.write_bytes(src.read_bytes())
    profile.resume_path = str(dest)
    return profile


def load_profile() -> Profile:
    root = find_project_root()
    path = root / "config" / "profile.yaml"
    if not path.exists():
        example = root / "config" / "profile.example.yaml"
        raise FileNotFoundError(
            f"Missing {path}. Copy the example and fill your details:\n"
            f"  cp {example} {path}"
        )
    raw = _load_yaml(path)
    profile = Profile.model_validate(raw)
    if not (profile.full_name and profile.email):
        raise ValueError(
            "config/profile.yaml needs at least full_name and email. "
            "See config/profile.example.yaml."
        )
    return ensure_resume_copy(profile, root / "data")
