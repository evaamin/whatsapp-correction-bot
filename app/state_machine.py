"""Core tracking logic: create requests, process replies, run follow-ups.

This module is the single source of truth for the state machine. The FastAPI
webhook, the follow-up scheduler, and the CLI dry-run script all call into
these functions rather than duplicating the logic — so testing/simulating
via the CLI exercises exactly the same code path as production.
"""

from __future__ import annotations

import logging

from app import classifier, db, messaging
from app.config import center_name_for_number, load_centers, settings
from app.models import CorrectionRequest, Status

logger = logging.getLogger("whatsapp_bot.state_machine")


class UnknownCenterError(ValueError):
    pass


def parse_coordinator_message(body: str) -> tuple[str, str]:
    """Splits "<center_key>: <request text>" into (center_key, text).

    Also accepts "<center_key> <request text>" (space instead of colon).
    """
    body = body.strip()
    if ":" in body:
        key, _, text = body.partition(":")
        return key.strip(), text.strip()
    if " " in body:
        key, _, text = body.partition(" ")
        return key.strip(), text.strip()
    raise ValueError(
        "Message must start with a center name, e.g. 'clinicA: please fix the "
        "intake form field'."
    )


def handle_coordinator_request(coordinator_number: str, body: str) -> CorrectionRequest:
    """Coordinator -> bot: create a tracking record and forward to the center."""
    center_key, request_text = parse_coordinator_message(body)
    centers = load_centers()
    center_number = centers.get(center_key)
    if not center_number:
        raise UnknownCenterError(
            f"Unknown center '{center_key}'. Known centers: {', '.join(centers) or '(none configured)'}"
        )
    if not request_text:
        raise ValueError("Request text is empty — nothing to forward.")

    record = db.create_request(
        center=center_key,
        center_number=center_number,
        coordinator_number=coordinator_number,
        request_text=request_text,
    )

    messaging.send_message(
        center_number,
        f"New correction request (#{record.id}) from the coordinator:\n\n{request_text}",
    )
    messaging.send_message(
        coordinator_number,
        f"Request #{record.id} sent to {center_key}. I'll track the status and follow up.",
    )
    logger.info("Created request #%s for %s", record.id, center_key)
    return record


def handle_center_reply(center_number: str, reply_text: str) -> CorrectionRequest | None:
    """Center -> bot: classify the reply, update status, notify the coordinator.

    Returns the updated request, or None if no open request exists for this
    center number (message logged and dropped).
    """
    record = db.get_latest_open_request_for_center(center_number)
    if record is None:
        center_key = center_name_for_number(center_number) or center_number
        logger.warning("Reply from %s but no open request found: %r", center_key, reply_text)
        return None

    classification = classifier.classify_reply(record.request_text, reply_text)

    if classification == classifier.SUBSTANTIVE:
        db.update_status(
            record.id,
            status=Status.RESOLVED,
            response_text=reply_text,
            resolved=True,
        )
        messaging.send_message(
            record.coordinator_number,
            f"Request #{record.id} ({record.center}) resolved. Reply:\n\n{reply_text}",
        )
    else:
        db.update_status(
            record.id,
            status=Status.ACKNOWLEDGED,
            response_text=reply_text,
            reset_followups=True,
        )
        messaging.send_message(
            record.coordinator_number,
            f"Request #{record.id} ({record.center}) acknowledged: \"{reply_text}\"",
        )

    updated = db.get_request(record.id)
    logger.info("Request #%s -> %s", record.id, updated.status)
    return updated


def check_followups() -> list[CorrectionRequest]:
    """Scans open requests; nudges quiet centers or flips them to overdue.

    Called on a timer by the scheduler, and can be invoked directly (e.g.
    from the CLI dry-run tool) to test the logic without waiting.
    """
    from datetime import datetime, timedelta, timezone

    threshold = timedelta(minutes=settings.followup_interval_minutes)
    now = datetime.now(timezone.utc)
    touched: list[CorrectionRequest] = []

    for record in db.list_open_requests():
        last_activity = datetime.fromisoformat(record.last_activity_timestamp)
        if now - last_activity < threshold:
            continue

        if record.follow_up_count >= settings.max_followups:
            db.mark_overdue(record.id)
            messaging.send_message(
                record.coordinator_number,
                f"Request #{record.id} ({record.center}) is now OVERDUE — no "
                f"response after {record.follow_up_count} follow-ups.",
            )
        else:
            messaging.send_message(
                record.center_number,
                f"Follow-up on request #{record.id}:\n\n{record.request_text}\n\n"
                f"(This is follow-up #{record.follow_up_count + 1}.)",
            )
            db.record_followup_sent(record.id)

        touched.append(db.get_request(record.id))

    return touched
