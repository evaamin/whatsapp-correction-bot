#!/usr/bin/env python3
"""Local dry-run / test CLI for the correction bot.

Simulates incoming WhatsApp messages by calling the exact same state-machine
functions the FastAPI webhook uses, so you can exercise the full
request -> reply -> classify -> follow-up flow without any Twilio or
Anthropic credentials configured. If ANTHROPIC_API_KEY is unset, replies are
classified with a keyword heuristic (see app/classifier.py); if Twilio isn't
configured, outbound messages are printed instead of sent (see
app/messaging.py).

Examples:
    python cli_dry_run.py send clinicA "Please fix the intake form field"
    python cli_dry_run.py reply clinicA "ok will check"
    python cli_dry_run.py reply clinicA "Fixed — the field now requires a date"
    python cli_dry_run.py check-followups
    python cli_dry_run.py list
    python cli_dry_run.py export-csv out.csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db, state_machine
from app.config import load_centers, settings


def cmd_send(args: argparse.Namespace) -> None:
    body = f"{args.center}: {args.text}"
    try:
        record = state_machine.handle_coordinator_request(settings.coordinator_number, body)
    except (ValueError, state_machine.UnknownCenterError) as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"Created request #{record.id} for {record.center} (status={record.status})")


def cmd_reply(args: argparse.Namespace) -> None:
    centers = load_centers()
    center_number = centers.get(args.center)
    if not center_number:
        print(f"Unknown center '{args.center}'. Known centers: {', '.join(centers) or '(none)'}")
        sys.exit(1)

    updated = state_machine.handle_center_reply(center_number, args.text)
    if updated is None:
        print(f"No open request found for {args.center} — nothing to update.")
        sys.exit(1)
    print(f"Request #{updated.id} -> {updated.status} (follow_up_count={updated.follow_up_count})")


def cmd_check_followups(args: argparse.Namespace) -> None:
    touched = state_machine.check_followups()
    if not touched:
        print("No requests are due for a follow-up right now.")
        return
    for r in touched:
        print(f"Request #{r.id} ({r.center}) -> status={r.status}, follow_up_count={r.follow_up_count}")


def cmd_age(args: argparse.Namespace) -> None:
    """Backdates a request's last_activity_timestamp, for testing follow-ups
    without waiting for FOLLOWUP_INTERVAL_MINUTES to actually elapse."""
    record = db.get_request(args.request_id)
    if record is None:
        print(f"No request #{args.request_id}")
        sys.exit(1)
    new_ts = (datetime.now(timezone.utc) - timedelta(minutes=args.minutes)).isoformat()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE requests SET last_activity_timestamp = ? WHERE id = ?",
            (new_ts, args.request_id),
        )
    print(f"Request #{args.request_id} last_activity_timestamp backdated by {args.minutes} minutes.")


def cmd_list(args: argparse.Namespace) -> None:
    records = db.list_requests()
    if not records:
        print("No requests yet.")
        return
    header = f"{'ID':<4} {'CENTER':<12} {'STATUS':<13} {'FOLLOWUPS':<10} {'SENT':<20} {'RESPONSE'}"
    print(header)
    print("-" * len(header))
    for r in records:
        response = (r.response_text or "")[:40]
        print(
            f"{r.id:<4} {r.center:<12} {r.status:<13} {r.follow_up_count:<10} "
            f"{r.sent_timestamp[:19]:<20} {response}"
        )


def cmd_export_csv(args: argparse.Namespace) -> None:
    path = db.export_csv(Path(args.path))
    print(f"Exported to {path}")


def cmd_centers(args: argparse.Namespace) -> None:
    centers = load_centers()
    if not centers:
        print(f"No centers configured. Create {settings.centers_file_resolved} (see centers.example.json).")
        return
    for name, number in centers.items():
        print(f"{name}: {number}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_send = sub.add_parser("send", help="Simulate the coordinator sending a correction request")
    p_send.add_argument("center", help="Center key, as in centers.json")
    p_send.add_argument("text", help="Request text")
    p_send.set_defaults(func=cmd_send)

    p_reply = sub.add_parser("reply", help="Simulate a center replying")
    p_reply.add_argument("center", help="Center key, as in centers.json")
    p_reply.add_argument("text", help="Reply text")
    p_reply.set_defaults(func=cmd_reply)

    p_check = sub.add_parser("check-followups", help="Run the follow-up scheduler logic once, now")
    p_check.set_defaults(func=cmd_check_followups)

    p_age = sub.add_parser(
        "age", help="Backdate a request's last-activity timestamp (to test follow-ups without waiting)"
    )
    p_age.add_argument("request_id", type=int)
    p_age.add_argument("minutes", type=int, help="Minutes to backdate by")
    p_age.set_defaults(func=cmd_age)

    p_list = sub.add_parser("list", help="List all tracked requests")
    p_list.set_defaults(func=cmd_list)

    p_csv = sub.add_parser("export-csv", help="Export the tracking log to CSV")
    p_csv.add_argument("path", nargs="?", default="tracking_export.csv")
    p_csv.set_defaults(func=cmd_export_csv)

    p_centers = sub.add_parser("centers", help="List configured centers")
    p_centers.set_defaults(func=cmd_centers)

    return parser


def main() -> None:
    db.init_db()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
