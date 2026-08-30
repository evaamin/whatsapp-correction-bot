"""Data shapes for tracking records."""

from __future__ import annotations

from dataclasses import dataclass


class Status:
    """Request lifecycle states. Plain string constants (stored as-is in SQLite)."""

    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    OVERDUE = "overdue"

    ALL = (SENT, ACKNOWLEDGED, RESOLVED, OVERDUE)
    OPEN = (SENT, ACKNOWLEDGED)  # statuses eligible for follow-up nudges


@dataclass
class CorrectionRequest:
    id: int
    center: str
    center_number: str
    coordinator_number: str
    request_text: str
    sent_timestamp: str
    status: str
    follow_up_count: int
    response_text: str | None
    resolved_timestamp: str | None
    last_activity_timestamp: str
