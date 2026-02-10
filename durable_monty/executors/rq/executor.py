"""RQ executor for distributed task execution."""

import logging
from typing import Any

from durable_monty.executor import Executor

logger = logging.getLogger(__name__)


class RQExecutor(Executor):
    """Executes functions using Redis Queue (RQ)."""

    def __init__(self, redis_conn=None, queue_name: str = "durable-monty"):
        """
        Initialize RQ executor.

        Args:
            redis_conn: Redis connection (will create default if None)
            queue_name: Name of the RQ queue
        """
        try:
            from redis import Redis
            from rq import Queue
        except ImportError:
            raise ImportError(
                "RQ executor requires 'rq' and 'redis' packages. "
                "Install with: pip install rq redis"
            )

        self.redis_conn = redis_conn or Redis()
        self.queue = Queue(queue_name, connection=self.redis_conn)
        logger.info(f"RQ executor initialized with queue '{queue_name}'")

    def submit_call(self, function_name: str, args: list, kwargs: dict | None = None) -> str:
        """Submit call to RQ and return job_id."""
        from durable_monty.executors.rq.worker import execute_call_task

        job = self.queue.enqueue(
            execute_call_task,
            args=[function_name, args, kwargs],
            job_timeout="10m",
        )

        logger.info(f"Enqueued {function_name} to RQ [job={job.id[:8]}]")

        return job.id

    def check_job(self, job_id: str) -> dict[str, Any]:
        """
        Check status of an RQ job.

        Returns:
            {"status": "finished|failed|queued|started", "result": ...}
        """
        from rq.job import Job

        try:
            job = Job.fetch(job_id, connection=self.redis_conn)

            if job.is_finished:
                return {"status": "finished", "result": job.result}
            elif job.is_failed:
                return {"status": "failed", "error": str(job.exc_info)}
            elif job.is_started:
                return {"status": "started"}
            else:
                return {"status": "queued"}

        except Exception as e:
            logger.error(f"Failed to fetch job {job_id}: {e}")
            return {"status": "error", "error": str(e)}

    def get_stats(self) -> dict[str, Any]:
        """Get RQ queue statistics."""
        return {
            "queued": len(self.queue),
            "failed": self.queue.failed_job_registry.count,
            "finished": self.queue.finished_job_registry.count,
        }
