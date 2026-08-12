import logging
import signal
import time

from app.core.config import get_settings
from app.services.jobs.manager import JobManager
from app.services.workspace_lifecycle import process_due_deletions
from app.services.operations import send_operational_alert

logger = logging.getLogger("datapilot.worker")
stopping = False


def _stop(*_args):
    global stopping; stopping = True


def main() -> int:
    settings = get_settings()
    if settings.job_execution_mode.casefold() != "redis" or not settings.redis_url:
        logger.error("Worker requires JOB_EXECUTION_MODE=redis and REDIS_URL"); return 2
    from redis import Redis
    redis = Redis.from_url(settings.redis_url, decode_responses=True); queue = settings.job_queue_name
    signal.signal(signal.SIGINT, _stop); signal.signal(signal.SIGTERM, _stop)
    logger.info("worker_started"); next_cleanup = 0.0
    while not stopping:
        now = time.time(); redis.set(f"{queue}:worker:heartbeat", str(now), ex=settings.worker_heartbeat_ttl_seconds)
        if now >= next_cleanup:
            try: process_due_deletions()
            except Exception:
                logger.exception("scheduled_deletion_cleanup_failed"); send_operational_alert("DELETION_CLEANUP_FAILED", "Scheduled deletion cleanup failed.")
            next_cleanup = now + 60
        backlog = redis.llen(queue)
        if backlog >= settings.job_queue_backlog_alert: send_operational_alert("JOB_QUEUE_BACKLOG", "The durable job queue exceeded its backlog threshold.", {"backlog": backlog, "threshold": settings.job_queue_backlog_alert})
        due = redis.zrangebyscore(f"{queue}:delayed", 0, now, start=0, num=100)
        if due:
            pipe = redis.pipeline()
            for job_id in due: pipe.zrem(f"{queue}:delayed", job_id); pipe.rpush(queue, job_id)
            pipe.execute()
        item = redis.blpop(queue, timeout=5)
        if item: JobManager().run_job(item[1])
    logger.info("worker_stopped"); return 0


if __name__ == "__main__": raise SystemExit(main())
