"""Standalone Background Job Worker Process (D4/D6).

Processes queued asynchronous tasks (e.g. STT, LLM evaluation, resume
extraction) independently from the API server.
"""
import logging
import signal
import sys
import time

from app.config import settings
from app.core.jobs.queue import get_job_queue
from app.core.jobs.worker import JobWorker
from app.core.logging import setup_logging

logger = logging.getLogger("worker")


def main() -> None:
    setup_logging(log_level=settings.log_level)
    logger.info(
        "Starting standalone worker process in environment='%s'",
        settings.environment,
    )

    if settings.environment == "production":
        settings.validate_production_readiness()

    queue = get_job_queue()
    worker = JobWorker(queue=queue)

    running = True

    def shutdown_handler(signum, frame):
        nonlocal running
        logger.info("Shutdown signal received (%s). Exiting worker...", signum)
        running = False

    signal.signal(signal.SIGINT, shutdown_handler)
    try:
        signal.signal(signal.SIGTERM, shutdown_handler)
    except AttributeError:
        pass  # Windows may not have SIGTERM

    logger.info("Worker polling queue for background jobs...")
    while running:
        processed = worker.process_next()
        if not processed:
            time.sleep(1.0)

    logger.info("Worker exited cleanly.")


if __name__ == "__main__":
    main()
