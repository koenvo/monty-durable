"""Worker for executing durable functions."""

import logging
import time
from typing import Callable
from sqlalchemy.orm import Session

from durable_monty.service import OrchestratorService
from durable_monty.models import Execution, Call, from_json
from durable_monty.executor import Executor, LocalExecutor

logger = logging.getLogger(__name__)


class Worker:
    """Worker that picks up and executes scheduled executions and pending calls."""

    def __init__(
        self,
        service: OrchestratorService,
        executor: Executor,
        poll_interval: float = 1.0,
    ):
        self.service = service
        self.executor = executor
        self.poll_interval = poll_interval
        self.running = False
        self._seen_completed = set()  # Track completed executions

    def run(self, once: bool = False) -> None:
        """
        Run worker loop.

        Args:
            once: If True, run one iteration and return. If False, run forever.
        """
        if once:
            self._process_scheduled()
            self._process_pending_calls()
            self._process_submitted_jobs()
            self._process_waiting()
            return

        self.running = True
        logger.info("Worker started")

        while self.running:
            try:
                self._process_scheduled()
                self._process_pending_calls()
                self._process_submitted_jobs()
                self._process_waiting()
                time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                logger.info("Worker stopping...")
                self.running = False
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                time.sleep(self.poll_interval)

    def _process_scheduled(self) -> None:
        """Start scheduled executions."""
        with Session(self.service.engine) as session:
            scheduled = session.query(Execution).filter_by(status="scheduled").all()

            for execution in scheduled:
                try:
                    logger.info(f"Starting execution {execution.id[:8]}...")
                    self.service._process_execution(execution.id)
                except Exception as e:
                    logger.error(f"Error starting {execution.id[:8]}: {e}")

    def _process_pending_calls(self) -> None:
        """Submit pending calls to executor."""
        with Session(self.service.engine) as session:
            pending_calls = session.query(Call).filter_by(status="pending").limit(10).all()

            for call in pending_calls:
                try:
                    # Submit to executor with function_name and args
                    args = from_json(call.args)
                    job_id = self.executor.submit_call(call.function_name, args)

                    # Store job_id
                    call.job_id = job_id
                    call.status = "submitted"
                    session.commit()

                except Exception as e:
                    # Mark as failed
                    logger.error(f"Failed to submit call {call.call_id}: {e}")
                    call.status = "failed"
                    call.error = str(e)
                    session.commit()

    def _process_submitted_jobs(self) -> None:
        """Check submitted jobs and update completed ones."""
        # Only for executors that support job checking (RQ, Modal, etc.)
        if not hasattr(self.executor, 'check_job'):
            return

        with Session(self.service.engine) as session:
            submitted_calls = (
                session.query(Call)
                .filter(Call.status == "submitted", Call.job_id.isnot(None))
                .limit(50)
                .all()
            )

            for call in submitted_calls:
                try:
                    job_status = self.executor.check_job(call.job_id)

                    if job_status["status"] == "finished":
                        # Job completed successfully
                        result = job_status["result"]
                        self.service.complete_call(
                            call.execution_id,
                            call.call_id,
                            result,
                        )
                        logger.info(
                            f"Job {call.job_id[:8]} completed: {call.function_name} = {result}"
                        )

                    elif job_status["status"] == "failed":
                        # Job failed
                        error = job_status.get("error", "Unknown error")
                        call.status = "failed"
                        call.error = error
                        session.commit()
                        logger.error(f"Job {call.job_id[:8]} failed: {error}")

                except Exception as e:
                    logger.error(f"Error checking job {call.job_id}: {e}")

    def _process_waiting(self) -> None:
        """Check waiting executions and resume if ready."""
        results = self.service.poll()

        for result in results:
            if result["status"] == "completed":
                exec_id = result["execution_id"]
                if exec_id not in self._seen_completed:
                    self._seen_completed.add(exec_id)
                    logger.info(
                        f"Execution {exec_id[:8]} completed with output: {result['output']}"
                    )

    def stop(self) -> None:
        """Stop the worker."""
        self.running = False
