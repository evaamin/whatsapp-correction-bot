"""Loads configuration from environment variables (.env) and centers.json.

Nothing in this module hardcodes a credential. Every secret comes from the
environment, populated from `.env` in local/dev use. See `.env.example`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


@dataclass
class Settings:
    # Twilio
    twilio_account_sid: str = field(default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID", ""))
    twilio_auth_token: str = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", ""))
    twilio_whatsapp_number: str = field(
        default_factory=lambda: os.getenv("TWILIO_WHATSAPP_NUMBER", "")
    )
    twilio_api_key_sid: str = field(default_factory=lambda: os.getenv("TWILIO_API_KEY_SID", ""))
    twilio_api_key_secret: str = field(
        default_factory=lambda: os.getenv("TWILIO_API_KEY_SECRET", "")
    )

    # Outbound provider: "twilio" or "meta" (Meta's WhatsApp Cloud API directly)
    whatsapp_provider: str = field(
        default_factory=lambda: os.getenv("WHATSAPP_PROVIDER", "twilio").strip().lower()
    )

    # Meta WhatsApp Cloud API
    whatsapp_access_token: str = field(
        default_factory=lambda: os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    )
    whatsapp_phone_number_id: str = field(
        default_factory=lambda: os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    )
    whatsapp_verify_token: str = field(
        default_factory=lambda: os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    )

    # Anthropic
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
    )

    # Coordinator
    coordinator_number: str = field(
        default_factory=lambda: os.getenv("COORDINATOR_WHATSAPP_NUMBER", "")
    )

    # Scheduler
    followup_interval_minutes: int = field(
        default_factory=lambda: _env_int("FOLLOWUP_INTERVAL_MINUTES", 1440)
    )
    max_followups: int = field(default_factory=lambda: _env_int("MAX_FOLLOWUPS", 3))
    followup_check_interval_seconds: int = field(
        default_factory=lambda: _env_int("FOLLOWUP_CHECK_INTERVAL_SECONDS", 300)
    )

    # Storage
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "data/tracking.db"))
    centers_file: str = field(default_factory=lambda: os.getenv("CENTERS_FILE", "centers.json"))

    @property
    def db_path_resolved(self) -> Path:
        p = Path(self.db_path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def centers_file_resolved(self) -> Path:
        p = Path(self.centers_file)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_whatsapp_number)

    @property
    def meta_configured(self) -> bool:
        return bool(self.whatsapp_access_token and self.whatsapp_phone_number_id)

    @property
    def whatsapp_configured(self) -> bool:
        if self.whatsapp_provider == "meta":
            return self.meta_configured
        return self.twilio_configured

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()


def load_centers() -> dict[str, str]:
    """Maps center name -> WhatsApp number (e.g. {"clinicA": "whatsapp:+1..."})."""
    path = settings.centers_file_resolved
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def center_name_for_number(number: str) -> str | None:
    centers = load_centers()
    for name, phone in centers.items():
        if phone == number:
            return name
    return None
