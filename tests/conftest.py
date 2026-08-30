import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Points the app at a scratch DB + centers file for every test, and
    ensures no real credentials leak in from a developer's local .env."""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "twilio_account_sid", "")
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    monkeypatch.setattr(settings, "twilio_whatsapp_number", "")
    monkeypatch.setattr(settings, "whatsapp_provider", "twilio")
    monkeypatch.setattr(settings, "whatsapp_access_token", "")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "")
    monkeypatch.setattr(settings, "whatsapp_verify_token", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "coordinator_number", "whatsapp:+15550000000")
    monkeypatch.setattr(settings, "followup_interval_minutes", 60)
    monkeypatch.setattr(settings, "max_followups", 2)

    centers_path = tmp_path / "centers.json"
    centers_path.write_text(
        json.dumps({"clinicA": "whatsapp:+15551230001", "clinicB": "whatsapp:+15551230002"})
    )
    monkeypatch.setattr(settings, "centers_file", str(centers_path))

    db.init_db()
    yield
