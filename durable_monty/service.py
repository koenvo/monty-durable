"""Orchestrator service that manages executions."""

import uuid
import inspect
import os
import sys
from typing import Any, Callable
from pathlib import Path
import pydantic_monty
from sqlalchemy.orm import Session
from sqlalchemy import Engine

from durable_monty.models import Execution, Call, ExecutionStatus, CallStatus, to_json, from_json


def _resolve_function_path(func: Callable) -> str:
    """
    Resolve the full import path for a function, handling __main__ modules.

    When a script is run directly (python script.py), functions defined in it
    have __module__ = "__main__". This converts it to the actual module path
    that can be imported by workers.

    Args:
        func: Function object

    Returns:
        Full import path like "examples.with_rq.add"

    Raises:
        ValueError: If module path cannot be resolved
    """
    module_name = func.__module__
    func_name = func.__name__

    # If not __main__, use as-is
    if module_name != "__main__":
        return f"{module_name}.{func_name}"

    # Try to resolve __main__ to actual module path
    try:
        # Get the file where the function is defined
        source_file = inspect.getfile(func)
        source_path = Path(source_file).resolve()

        # Find which sys.path entry contains this file
        for path_entry in sys.path:
            try:
                path_entry = Path(path_entry).resolve()
                if source_path.is_relative_to(path_entry):
                    # Convert file path to module path
                    rel_path = source_path.relative_to(path_entry)

                    # Remove .py extension and convert to module notation
                    module_parts = list(rel_path.parts[:-1]) + [rel_path.stem]
                    resolved_module = ".".join(module_parts)

                    return f"{resolved_module}.{func_name}"
            except (ValueError, OSError):
                continue

        # Could not resolve - provide helpful error
        raise ValueError(
            f"Cannot resolve module path for function '{func_name}' defined in __main__.\n"
            f"The function is in '{source_file}' which is not in any Python path.\n"
            f"Either:\n"
            f"  1. Import the function from its module instead of running the script directly\n"
            f"  2. Ensure the script's directory is in PYTHONPATH\n"
            f"  3. Pass the full import path as a string instead of the function object"
        )

    except (TypeError, OSError) as e:
        raise ValueError(
            f"Cannot determine source file for function '{func_name}': {e}\n"
            f"Pass the full import path as a string instead of the function object."
        )


class OrchestratorService:
    """Service for managing durable executions."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def start_execution(
        self,
        code: str,
        external_functions: list[str | Callable],  # Accept strings or callable objects
        inputs: dict | None = None,
    ) -> str:
        """
        Schedule a new workflow execution. Returns execution_id.

        Args:
            code: Python code to execute
            external_functions: List of function names (as full paths or callable objects)
            inputs: Optional input variables for the code

        Example:
            # Pass actual function objects (recommended)
            exec_id = service.start_execution(code, [add, multiply])

            # Or pass full import paths as strings
            exec_id = service.start_execution(code, ["myapp.tasks.add"])
        """
        execution_id = str(uuid.uuid4())

        # Convert callable objects to {short_name: full_path} mapping
        function_mapping = {}
        for func in external_functions:
            if callable(func):
                # Extract full path and short name from function object
                # This handles __main__ module resolution
                full_path = _resolve_function_path(func)
                short_name = func.__name__
                function_mapping[short_name] = full_path
            else:
                # String path - extract short name
                short_name = func.rsplit(".", 1)[-1] if "." in func else func
                function_mapping[short_name] = func

        with Session(self.engine) as session:
            # Save mapping to DB - worker will use it
            execution = Execution(
                id=execution_id,
                code=code,
                external_functions=to_json(function_mapping),
                status=ExecutionStatus.SCHEDULED,
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

            # Load function mapping {short_name: full_path} for converting names
            function_mapping = from_json(execution.external_functions)

            # Get Monty progress based on execution status
            if execution.status == ExecutionStatus.SCHEDULED:
                # First time - start fresh
                inputs = from_json(execution.inputs)
                m = pydantic_monty.Monty(
                    execution.code,
                    external_functions=list(function_mapping.keys()),  # Pass short names to Monty
                    inputs=list(inputs.keys()) if inputs else None,
                )
                progress = m.start(inputs=inputs) if inputs else m.start()

            elif execution.status == ExecutionStatus.WAITING:
                # Resume with results
                if not resume_group_id:
                    return

                # Load completed results
                calls = (
                    session.query(Call)
                    .filter_by(resume_group_id=resume_group_id, status=ExecutionStatus.COMPLETED)
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
                execution.status = ExecutionStatus.COMPLETED
                execution.output = to_json(progress.output)
                session.commit()

            elif isinstance(progress, pydantic_monty.MontyFutureSnapshot):
                # More external calls needed - create new resume group
                new_resume_group_id = str(uuid.uuid4())
                execution.state = progress.dump()
                execution.status = ExecutionStatus.WAITING
                execution.current_resume_group_id = new_resume_group_id

                # Save all calls in this group
                for call_id in progress.pending_call_ids:
                    call_info = pending_calls[call_id]
                    # Convert short name to full path for execution
                    short_name = call_info["function"]
                    full_path = function_mapping.get(short_name, short_name)
                    call = Call(
                        execution_id=execution_id,
                        resume_group_id=new_resume_group_id,
                        call_id=call_id,
                        function_name=full_path,  # Store full path for RQ workers
                        args=to_json(call_info["args"]),
                        kwargs=to_json(call_info["kwargs"]),
                        status=CallStatus.PENDING,
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
            if execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED):
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
            completed = sum(1 for c in calls if c.status == CallStatus.COMPLETED)
            failed = sum(1 for c in calls if c.status == CallStatus.FAILED)
            pending = [
                {
                    "call_id": c.call_id,
                    "function_name": c.function_name,
                    "args": from_json(c.args),
                    "kwargs": from_json(c.kwargs),
                    "status": c.status,
                }
                for c in calls
                if c.status == CallStatus.PENDING
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
                execution.status = ExecutionStatus.FAILED
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

            if execution.status == ExecutionStatus.COMPLETED:
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
        """Poll all waiting executions."""
        with Session(self.engine) as session:
            executions = session.query(Execution).filter_by(status=ExecutionStatus.WAITING).all()
            return [self.poll(e.id) for e in executions]

    def get_pending_calls(self, execution_id: str) -> list[dict]:
        """Get all pending calls for an execution."""
        with Session(self.engine) as session:
            calls = (
                session.query(Call)
                .filter_by(execution_id=execution_id, status=CallStatus.PENDING)
                .all()
            )
            return [
                {
                    "call_id": c.call_id,
                    "function_name": c.function_name,
                    "args": from_json(c.args),
                    "kwargs": from_json(c.kwargs),
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
                call.status = CallStatus.COMPLETED
                call.result = to_json(result)
                session.commit()

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        """
        Get execution info by ID.

        Returns:
            {
                "execution_id": str,
                "status": "scheduled" | "waiting" | "completed" | "failed",
                "output": result if completed, else None,
                "error": error message if failed, else None
            }

        Raises:
            ValueError: If execution not found
        """
        with Session(self.engine) as session:
            execution = session.query(Execution).filter_by(id=execution_id).first()
            if not execution:
                raise ValueError(f"Execution {execution_id} not found")

            return {
                "execution_id": execution.id,
                "status": execution.status,
                "output": from_json(execution.output) if execution.output else None,
                "error": execution.error if hasattr(execution, "error") else None,
            }

    def get_result(self, execution_id: str) -> Any:
        """
        Get the output of a completed execution.

        Returns:
            The execution output

        Raises:
            ValueError: If execution not found or not completed
        """
        execution = self.get_execution(execution_id)
        if execution["status"] != ExecutionStatus.COMPLETED:
            raise ValueError(
                f"Execution {execution_id} is not completed (status: {execution['status'].value})"
            )
        return execution["output"]
