"""
Durable-monty: Durable functions using monty-python.

Write normal Python async/await code that can pause, persist state,
execute tasks in parallel, and resume when results are ready.
"""

__version__ = "0.1.0"

from durable_monty.models import init_db, Execution, Call
from durable_monty.service import OrchestratorService
from durable_monty.functions import register_function, FUNCTION_REGISTRY
from durable_monty.worker import Worker
from durable_monty.executor import Executor, LocalExecutor
from durable_monty.api import create_app

__all__ = [
    "__version__",
    "init_db",
    "Execution",
    "Call",
    "OrchestratorService",
    "Worker",
    "Executor",
    "LocalExecutor",
    "register_function",
    "FUNCTION_REGISTRY",
    "create_app",
]
