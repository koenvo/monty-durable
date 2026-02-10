"""Orchestrator service that manages executions."""

import uuid
from typing import Any
import pydantic_monty
from sqlalchemy.orm import Session
from sqlalchemy import Engine

from durable_monty.models import Execution, Call, to_json, from_json


class OrchestratorService:
    """Service for managing durable executions."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def start_execution(
        self,
        code: str,
        external_functions: list[str],
        inputs: dict | None = None,
    ) -> str:
        """Schedule a new workflow execution. Returns execution_id."""
        execution_id = str(uuid.uuid4())

        with Session(self.engine) as session:
            # Just save to DB - worker will pick it up
            execution = Execution(
                id=execution_id,
                code=code,
                external_functions=to_json(external_functions),
                status="scheduled",
                inputs=to_json(inputs),
            )
            session.add(execution)
            session.commit()
            return execution_id

    def process_execution(
        self,
        execution_id: str,
        resume_group_id: str | None = None,
    ) -> None:
        """
        Process an execution - handles both scheduled (first start) and waiting (resume).

        For scheduled: Starts execution from scratch
        For waiting: Resumes execution with completed results
        """
        with Session(self.engine) as session:
            execution = session.query(Execution).filter_by(id=execution_id).first()
            if not execution:
                return

            # Get Monty progress based on execution status
            if execution.status == "scheduled":
                # First time - start fresh
                external_functions = from_json(execution.external_functions)
                inputs = from_json(execution.inputs)
                m = pydantic_monty.Monty(
                    execution.code,
                    external_functions=external_functions,
                    inputs=list(inputs.keys()) if inputs else None,
                )
                progress = m.start(inputs=inputs) if inputs else m.start()

            elif execution.status == "waiting":
                # Resume with results
                if not resume_group_id:
                    return

                # Load completed results
                calls = (
                    session.query(Call)
                    .filter_by(resume_group_id=resume_group_id, status="completed")
                    .all()
                )
                results = {
                    call.call_id: {"return_value": from_json(call.result)}
                    for call in calls
                }

                # Deserialize and resume
                progress = pydantic_monty.MontyFutureSnapshot.load(execution.state)
                progress = progress.resume(results=results)

            else:
                # Invalid status
                return

            # Collect all external calls and mark as futures
            pending_calls = {}
            while isinstance(progress, pydantic_monty.MontySnapshot):
                call_id = progress.call_id
                pending_calls[call_id] = {
                    "function": progress.function_name,
                    "args": progress.args,
                    "kwargs": progress.kwargs,
                }
                progress = progress.resume(future=...)

            # Handle final progress state
            if isinstance(progress, pydantic_monty.MontyComplete):
                # Execution finished!
                execution.status = "completed"
                execution.output = to_json(progress.output)
                session.commit()

            elif isinstance(progress, pydantic_monty.MontyFutureSnapshot):
                # More external calls needed - create new resume group
                new_resume_group_id = str(uuid.uuid4())
                execution.state = progress.dump()
                execution.status = "waiting"
                execution.current_resume_group_id = new_resume_group_id

                # Save all calls in this group
                for call_id in progress.pending_call_ids:
                    call_info = pending_calls[call_id]
                    call = Call(
                        execution_id=execution_id,
                        resume_group_id=new_resume_group_id,
                        call_id=call_id,
                        function_name=call_info["function"],
                        args=to_json(call_info["args"]),
                        status="pending",
                    )
                    session.add(call)

                session.commit()

    def poll(self, execution_id: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Poll execution status and resume if ready.

        Args:
            execution_id: Specific execution to poll, or None to poll all waiting executions

        Returns:
            Single execution: {
                "execution_id": str,
                "status": "pending" | "completed" | "failed",
                "output": result if completed, else None,
                "pending_calls": [...] if pending
            }
            All executions: list of the above dicts
        """
        if execution_id is None:
            # Poll all waiting executions
            return self._poll_all()

        with Session(self.engine) as session:
            execution = session.query(Execution).filter_by(id=execution_id).first()
            if not execution:
                raise ValueError(f"Execution {execution_id} not found")

            # If completed or failed, return result
            if execution.status in ("completed", "failed"):
                return {
                    "execution_id": execution_id,
                    "status": execution.status,
                    "output": from_json(execution.output),
                    "pending_calls": [],
                }

            # Check if all calls in current resume group are completed
            resume_group_id = execution.current_resume_group_id
            if not resume_group_id:
                return {
                    "execution_id": execution_id,
                    "status": "pending",
                    "output": None,
                    "pending_calls": [],
                }

            calls = session.query(Call).filter_by(resume_group_id=resume_group_id).all()

            total = len(calls)
            completed = sum(1 for c in calls if c.status == "completed")
            failed = sum(1 for c in calls if c.status == "failed")
            pending = [
                {
                    "call_id": c.call_id,
                    "function_name": c.function_name,
                    "args": from_json(c.args),
                    "status": c.status,
                }
                for c in calls
                if c.status == "pending"
            ]

            # Not all done yet
            if total != completed + failed:
                return {
                    "execution_id": execution_id,
                    "status": "pending",
                    "output": None,
                    "pending_calls": pending,
                }

            # All done - check for failures
            if failed > 0:
                execution.status = "failed"
                session.commit()
                return {
                    "execution_id": execution_id,
                    "status": "failed",
                    "output": None,
                    "pending_calls": [],
                }

            # All completed - resume!
            self.process_execution(execution_id, resume_group_id)

            # Re-query to get updated status
            execution = session.query(Execution).filter_by(id=execution_id).first()

            if execution.status == "completed":
                return {
                    "execution_id": execution_id,
                    "status": "completed",
                    "output": from_json(execution.output),
                    "pending_calls": [],
                }
            else:
                # Resumed to another waiting state
                return self.poll(execution_id)

    def _poll_all(self) -> list[dict[str, Any]]:
        """Poll all executions."""
        with Session(self.engine) as session:
            executions = session.query(Execution).all()
            return [self.poll(e.id) for e in executions]

    def get_pending_calls(self, execution_id: str) -> list[dict]:
        """Get all pending calls for an execution."""
        with Session(self.engine) as session:
            calls = (
                session.query(Call)
                .filter_by(execution_id=execution_id, status="pending")
                .all()
            )
            return [
                {
                    "call_id": c.call_id,
                    "function_name": c.function_name,
                    "args": from_json(c.args),
                }
                for c in calls
            ]

    def complete_call(self, execution_id: str, call_id: int, result: Any) -> None:
        """Mark a call as completed with a result."""
        with Session(self.engine) as session:
            call = (
                session.query(Call)
                .filter_by(execution_id=execution_id, call_id=call_id)
                .first()
            )
            if call:
                call.status = "completed"
                call.result = to_json(result)
                session.commit()
