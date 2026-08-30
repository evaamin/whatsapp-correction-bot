"""Background scheduler that periodically triggers follow-up nudges."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app import state_machine
from app.config import settings

logger = logging.getLogger("whatsapp_bot.scheduler")

_scheduler: BackgroundScheduler | None = None


def _run_followup_check() -> None:
    try:
        touched = state_machine.check_followups()
        if touched:
            logger.info("Follow-up check touched %d request(s)", len(touched))
    except Exception:
        logger.exception("Follow-up check failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _run_followup_check,
        "interval",
        seconds=settings.followup_check_interval_seconds,
        id="followup_check",
    )
    _scheduler.start()
    logger.info(
        "Scheduler started: checking for follow-ups every %ss",
        settings.followup_check_interval_seconds,
    )
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
        _scheduler = None
