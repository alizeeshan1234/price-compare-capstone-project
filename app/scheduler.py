"""Background job that checks every product on an interval."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import config
from .database import session_scope
from .services import check_all_products

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")

JOB_ID = "check_all_products"


def _job() -> None:
    log.info("scheduled price check starting")
    with session_scope() as db:
        summary = check_all_products(db)
    log.info("scheduled price check done: %s", summary)


def start() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        _job,
        IntervalTrigger(minutes=config.CHECK_INTERVAL_MINUTES),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    log.info("scheduler started: every %s minutes", config.CHECK_INTERVAL_MINUTES)


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def run_now() -> None:
    """Trigger the job immediately (used by the 'Check all now' button)."""
    _job()


def next_run_time():
    job = scheduler.get_job(JOB_ID) if scheduler.running else None
    return job.next_run_time if job else None
