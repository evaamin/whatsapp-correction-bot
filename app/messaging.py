"""Thin wrapper around WhatsApp send APIs — either Twilio or Meta's WhatsApp
Cloud API directly, selected by WHATSAPP_PROVIDER.

Phone numbers are handled uniformly as "whatsapp:+1..." everywhere else in
the app (centers.json, COORDINATOR_WHATSAPP_NUMBER, the db); this module is
the only place that translates that into whatever shape each provider's API
wants.

When the selected provider isn't configured, `send_message` prints to the
console instead of sending — this is what lets cli_dry_run.py exercise the
whole flow without live credentials.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("whatsapp_bot.messaging")

META_GRAPH_API_VERSION = "v21.0"

_twilio_client = None


def _get_twilio_client():
    global _twilio_client
    if _twilio_client is None:
        from twilio.rest import Client

        _twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    return _twilio_client


def _send_via_twilio(to: str, body: str) -> None:
    client = _get_twilio_client()
    client.messages.create(from_=settings.twilio_whatsapp_number, to=to, body=body)


def _send_via_meta(to: str, body: str) -> None:
    import requests

    recipient = to.removeprefix("whatsapp:")
    url = (
        f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": body},
    }
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    response.raise_for_status()


def send_message(to: str, body: str) -> None:
    """Sends a WhatsApp message via the configured provider, or logs it if
    not configured.

    Delivery failures (e.g. a recipient not reachable via a dev/test number)
    are logged, not raised — one undeliverable notification shouldn't crash
    a request whose more important half (e.g. notifying the center) already
    succeeded.
    """
    if not settings.whatsapp_configured:
        print(f"[DRY RUN] would send to {to}:\n  {body}\n")
        return

    try:
        if settings.whatsapp_provider == "meta":
            _send_via_meta(to, body)
        else:
            _send_via_twilio(to, body)
    except Exception:
        logger.exception("Failed to send WhatsApp message to %s via %s", to, settings.whatsapp_provider)
        return
    logger.info("Sent WhatsApp message to %s via %s", to, settings.whatsapp_provider)
