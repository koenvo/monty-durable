"""Worker for executing durable functions."""

import logging
import threading
import time
from typing import Callable
from sqlalchemy.orm import Session

from durable_monty.service import OrchestratorService
from durable_monty.models import Execution, Call, ExecutionStatus, CallStatus, from_json
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
        self._stop_event = threading.Event()

    def run(self, once: bool = False, until_complete: bool = False) -> None:
        """
        Run worker loop.

        Args:
            once: If True, run one iteration and return. If False, run forever.
            until_complete: If True, run until all executions are completed, then stop.
        """
        if once and until_complete:
            raise ValueError(
                "Cannot use both once=True and until_complete=True. "
                "Use once=True for a single iteration, or until_complete=True to process all executions."
            )

        if once:
            self._process_one_iteration()
            return

        self._stop_event.clear()
        logger.info("Worker started" + (" (until complete)" if until_complete else ""))

        while not self._stop_event.is_set():
            try:
                self._process_one_iteration()

                # Check if we should stop (until_complete mode)
                if until_complete and not self._has_active_executions():
                    logger.info("All executions completed, worker stopped")
                    break

                # Wait for poll_interval or until stop is signaled
                self._stop_event.wait(timeout=self.poll_interval)

            except KeyboardInterrupt:
                logger.info("Worker stopping...")
                self.stop()
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                self._stop_event.wait(timeout=self.poll_interval)

        if not until_complete:
            logger.info("Worker stopped")

    def _process_one_iteration(self) -> None:
        """Process one iteration of work."""
        self._process_scheduled()
        self._process_pending_calls()
        self._process_submitted_jobs()
        self._process_waiting()

    def _process_scheduled(self) -> None:
        """Start scheduled executions."""
        with Session(self.service.engine) as session:
            scheduled = session.query(Execution).filter_by(status=ExecutionStatus.SCHEDULED).all()

            for execution in scheduled:
                try:
                    logger.info(f"Starting execution {execution.id[:8]}...")
                    self.service.process_execution(execution.id)
                except Exception as e:
                    logger.error(f"Error starting {execution.id[:8]}: {e}")

    def _process_pending_calls(self) -> None:
        """Submit pending calls to executor."""
        with Session(self.service.engine) as session:
            pending_calls = session.query(Call).filter_by(status=CallStatus.PENDING).limit(10).all()

            for call in pending_calls:
                try:
                    # Submit to executor with function_name, args, and kwargs
                    args = from_json(call.args)
                    kwargs = from_json(call.kwargs)
                    job_id = self.executor.submit_call(call.function_name, args, kwargs)

                    # Store job_id
                    call.job_id = job_id
                    call.status = CallStatus.SUBMITTED
                    session.commit()

                except Exception as e:
                    # Mark as failed
                    logger.error(f"Failed to submit call {call.call_id}: {e}")
                    call.status = CallStatus.FAILED
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
                .filter(Call.status == CallStatus.SUBMITTED, Call.job_id.isnot(None))
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
                        call.status = CallStatus.FAILED
                        call.error = error
                        session.commit()
                        logger.error(f"Job {call.job_id[:8]} failed: {error}")

                except Exception as e:
                    logger.error(f"Error checking job {call.job_id}: {e}")

    def _process_waiting(self) -> None:
        """Check waiting executions and resume if ready."""
        results = self.service.poll()

        for result in results:
            if result["status"] == ExecutionStatus.COMPLETED.value:
                exec_id = result["execution_id"]
                logger.info(
                    f"Execution {exec_id[:8]} completed with output: {result['output']}"
                )

    def stop(self) -> None:
        """Stop the worker gracefully."""
        logger.info("Worker stop requested")
        self._stop_event.set()

    def _has_active_executions(self) -> bool:
        """Check if there are any active (scheduled or waiting) executions."""
        with Session(self.service.engine) as session:
            active = (
                session.query(Execution)
                .filter(
                    Execution.status.in_([ExecutionStatus.SCHEDULED, ExecutionStatus.WAITING])
                )
                .count()
            )
            return active > 0
