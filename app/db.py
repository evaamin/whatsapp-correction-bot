"""SQLite-backed storage for correction request tracking records.

Kept as a small repository of plain functions (not an ORM) so it's easy to
inspect the .db file directly (e.g. `sqlite3 data/tracking.db`) and easy to
swap for a shared sheet or a different database later — every call site in
this codebase goes through this module, not through raw SQL.
"""

from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import CorrectionRequest, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center TEXT NOT NULL,
    center_number TEXT NOT NULL,
    coordinator_number TEXT NOT NULL,
    request_text TEXT NOT NULL,
    sent_timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    follow_up_count INTEGER NOT NULL DEFAULT 0,
    response_text TEXT,
    resolved_timestamp TEXT,
    last_activity_timestamp TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection(db_path: Path | None = None):
    path = db_path or settings.db_path_resolved
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(SCHEMA)


def _row_to_request(row: sqlite3.Row) -> CorrectionRequest:
    return CorrectionRequest(
        id=row["id"],
        center=row["center"],
        center_number=row["center_number"],
        coordinator_number=row["coordinator_number"],
        request_text=row["request_text"],
        sent_timestamp=row["sent_timestamp"],
        status=row["status"],
        follow_up_count=row["follow_up_count"],
        response_text=row["response_text"],
        resolved_timestamp=row["resolved_timestamp"],
        last_activity_timestamp=row["last_activity_timestamp"],
    )


def create_request(
    center: str,
    center_number: str,
    coordinator_number: str,
    request_text: str,
    db_path: Path | None = None,
) -> CorrectionRequest:
    ts = now_iso()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO requests
                (center, center_number, coordinator_number, request_text,
                 sent_timestamp, status, follow_up_count, last_activity_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (center, center_number, coordinator_number, request_text, ts, Status.SENT, ts),
        )
        row = conn.execute("SELECT * FROM requests WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_request(row)


def get_request(request_id: int, db_path: Path | None = None) -> CorrectionRequest | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        return _row_to_request(row) if row else None


def get_latest_open_request_for_center(
    center_number: str, db_path: Path | None = None
) -> CorrectionRequest | None:
    """Most recent request for this center that can still receive a reply.

    Includes OVERDUE so a late reply is still processed instead of dropped.
    """
    placeholders = ",".join("?" * len(Status.ALL[:3]))  # SENT, ACKNOWLEDGED, OVERDUE
    open_statuses = (Status.SENT, Status.ACKNOWLEDGED, Status.OVERDUE)
    with get_connection(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT * FROM requests
            WHERE center_number = ? AND status IN ({placeholders})
            ORDER BY id DESC LIMIT 1
            """,
            (center_number, *open_statuses),
        ).fetchone()
        return _row_to_request(row) if row else None


def list_requests(db_path: Path | None = None) -> list[CorrectionRequest]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM requests ORDER BY id").fetchall()
        return [_row_to_request(r) for r in rows]


def list_open_requests(db_path: Path | None = None) -> list[CorrectionRequest]:
    placeholders = ",".join("?" * len(Status.OPEN))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM requests WHERE status IN ({placeholders}) ORDER BY id",
            Status.OPEN,
        ).fetchall()
        return [_row_to_request(r) for r in rows]


def update_status(
    request_id: int,
    status: str,
    response_text: str | None = None,
    resolved: bool = False,
    reset_followups: bool = False,
    db_path: Path | None = None,
) -> None:
    ts = now_iso()
    fields = ["status = ?", "last_activity_timestamp = ?"]
    values: list = [status, ts]

    if response_text is not None:
        fields.append("response_text = ?")
        values.append(response_text)
    if resolved:
        fields.append("resolved_timestamp = ?")
        values.append(ts)
    if reset_followups:
        fields.append("follow_up_count = 0")

    values.append(request_id)
    with get_connection(db_path) as conn:
        conn.execute(f"UPDATE requests SET {', '.join(fields)} WHERE id = ?", values)


def record_followup_sent(request_id: int, db_path: Path | None = None) -> None:
    ts = now_iso()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE requests
            SET follow_up_count = follow_up_count + 1, last_activity_timestamp = ?
            WHERE id = ?
            """,
            (ts, request_id),
        )


def mark_overdue(request_id: int, db_path: Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE requests SET status = ?, last_activity_timestamp = ? WHERE id = ?",
            (Status.OVERDUE, now_iso(), request_id),
        )


def export_csv(csv_path: Path, db_path: Path | None = None) -> Path:
    """Dumps the full tracking log to CSV for easy inspection / sharing."""
    requests = list_requests(db_path)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "center",
                "center_number",
                "coordinator_number",
                "request_text",
                "sent_timestamp",
                "status",
                "follow_up_count",
                "response_text",
                "resolved_timestamp",
                "last_activity_timestamp",
            ]
        )
        for r in requests:
            writer.writerow(
                [
                    r.id,
                    r.center,
                    r.center_number,
                    r.coordinator_number,
                    r.request_text,
                    r.sent_timestamp,
                    r.status,
                    r.follow_up_count,
                    r.response_text,
                    r.resolved_timestamp,
                    r.last_activity_timestamp,
                ]
            )
    return csv_path
