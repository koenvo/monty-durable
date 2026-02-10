"""
Durable-monty: Durable functions using monty-python.

Write normal Python async/await code that can pause, persist state,
execute tasks in parallel, and resume when results are ready.
"""

__version__ = "0.1.2"

from durable_monty.models import init_db, Execution, Call, ExecutionStatus, CallStatus
from durable_monty.service import OrchestratorService
from durable_monty.functions import register_function, FUNCTION_REGISTRY
from durable_monty.worker import Worker
from durable_monty.executor import Executor, LocalExecutor

__all__ = [
    "__version__",
    "init_db",
    "Execution",
    "Call",
    "ExecutionStatus",
    "CallStatus",
    "OrchestratorService",
    "Worker",
    "Executor",
    "LocalExecutor",
    "register_function",
    "FUNCTION_REGISTRY",
]
