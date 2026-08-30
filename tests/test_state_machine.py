from datetime import datetime, timedelta, timezone

from app import db, state_machine
from app.config import settings
from app.models import Status

CLINIC_A = "whatsapp:+15551230001"


def test_full_flow_acknowledgement_then_resolution():
    record = state_machine.handle_coordinator_request(
        settings.coordinator_number, "clinicA: please fix the intake form"
    )
    assert record.status == Status.SENT
    assert record.center == "clinicA"
    assert record.center_number == CLINIC_A

    # A plain acknowledgement should not resolve the request.
    updated = state_machine.handle_center_reply(CLINIC_A, "ok, will check")
    assert updated.status == Status.ACKNOWLEDGED
    assert updated.response_text == "ok, will check"

    # A substantive reply should resolve it.
    updated = state_machine.handle_center_reply(
        CLINIC_A, "Fixed — the intake form field now requires a valid date."
    )
    assert updated.status == Status.RESOLVED
    assert updated.resolved_timestamp is not None


def test_unknown_center_raises():
    try:
        state_machine.handle_coordinator_request(
            settings.coordinator_number, "not_a_real_clinic: hello"
        )
        assert False, "expected UnknownCenterError"
    except state_machine.UnknownCenterError:
        pass


def test_reply_with_no_open_request_returns_none():
    result = state_machine.handle_center_reply(CLINIC_A, "hello, unprompted message")
    assert result is None


def test_followup_nudges_then_marks_overdue():
    record = state_machine.handle_coordinator_request(
        settings.coordinator_number, "clinicA: please fix the intake form"
    )

    def backdate(minutes: int) -> None:
        ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE requests SET last_activity_timestamp = ? WHERE id = ?",
                (ts, record.id),
            )

    # Not due yet — interval is 60 minutes.
    touched = state_machine.check_followups()
    assert touched == []

    # First nudge.
    backdate(61)
    touched = state_machine.check_followups()
    assert len(touched) == 1
    assert touched[0].follow_up_count == 1
    assert touched[0].status == Status.SENT

    # Second nudge (max_followups=2 in test config).
    backdate(61)
    touched = state_machine.check_followups()
    assert touched[0].follow_up_count == 2
    assert touched[0].status == Status.SENT

    # Third time: follow_up_count already at max -> overdue instead of a nudge.
    backdate(61)
    touched = state_machine.check_followups()
    assert touched[0].status == Status.OVERDUE
    assert touched[0].follow_up_count == 2  # unchanged — no nudge sent


def test_acknowledgement_resets_followup_count():
    record = state_machine.handle_coordinator_request(
        settings.coordinator_number, "clinicA: please fix the intake form"
    )
    with db.get_connection() as conn:
        conn.execute("UPDATE requests SET follow_up_count = 2 WHERE id = ?", (record.id,))

    # A plain ack means the center is responsive again, so the nudge
    # counter resets (it stays SENT/ACKNOWLEDGED and is still eligible for
    # future follow-ups if it goes quiet again).
    updated = state_machine.handle_center_reply(CLINIC_A, "ok")
    assert updated.status == Status.ACKNOWLEDGED
    assert updated.follow_up_count == 0
