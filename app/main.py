"""FastAPI app: WhatsApp webhooks (Twilio and/or Meta Cloud API) + a couple
of read-only inspection routes.

Run with: uvicorn app.main:app --reload

If WHATSAPP_PROVIDER=twilio, point your Twilio WhatsApp sandbox/number's
"when a message comes in" webhook at POST /webhook/whatsapp.

If WHATSAPP_PROVIDER=meta, point your Meta app's WhatsApp webhook at
/webhook/whatsapp/meta — Meta calls GET on it once to verify (using
WHATSAPP_VERIFY_TOKEN) and POSTs inbound messages there afterwards.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app import db, state_machine
from app.config import settings
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("whatsapp_bot.main")

app = FastAPI(title="WhatsApp Correction & Follow-up Bot")


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_scheduler()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "whatsapp_provider": settings.whatsapp_provider,
        "whatsapp_configured": settings.whatsapp_configured,
        "anthropic_configured": settings.anthropic_configured,
    }


@app.get("/requests")
def list_requests() -> list[dict]:
    return [r.__dict__ for r in db.list_requests()]


def _handle_inbound_message(sender: str, body: str) -> None:
    """Shared by every webhook provider: sender/body are already normalized
    to the "whatsapp:+1..." / plain-text shape used elsewhere in the app."""
    try:
        if sender == settings.coordinator_number:
            state_machine.handle_coordinator_request(sender, body)
        else:
            state_machine.handle_center_reply(sender, body)
    except state_machine.UnknownCenterError as e:
        from app import messaging

        messaging.send_message(sender, str(e))
    except ValueError as e:
        logger.warning("Rejected message from %s: %s", sender, e)


@app.post("/webhook/whatsapp")
def whatsapp_webhook(From: str = Form(...), Body: str = Form(...)) -> Response:
    """Twilio posts inbound WhatsApp messages here as form-encoded fields."""
    _handle_inbound_message(From, Body)

    # Twilio expects a TwiML (or empty) response; we already sent replies
    # proactively via the REST API in state_machine, so return empty TwiML.
    return Response(content="<Response></Response>", media_type="application/xml")


@app.get("/webhook/whatsapp/meta")
def whatsapp_webhook_meta_verify(request: Request) -> PlainTextResponse:
    """Meta calls this once, when you register the webhook URL in the App
    Dashboard, to confirm you control it."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == settings.whatsapp_verify_token and settings.whatsapp_verify_token:
        return PlainTextResponse(content=challenge)
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@app.post("/webhook/whatsapp/meta")
async def whatsapp_webhook_meta(request: Request) -> JSONResponse:
    """Meta posts inbound WhatsApp messages here as nested JSON. Non-message
    events (e.g. delivery/read statuses) are acknowledged and ignored."""
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue
                sender = f"whatsapp:+{message['from']}"
                body = message.get("text", {}).get("body", "")
                _handle_inbound_message(sender, body)

    return JSONResponse(content={"status": "ok"})


@app.exception_handler(Exception)
def unhandled_exception_handler(request, exc):  # pragma: no cover
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error": str(exc)})
