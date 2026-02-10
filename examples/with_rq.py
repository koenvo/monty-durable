"""Distributed execution with Redis Queue.

Setup:
1. Start Redis: redis-server
2. Start RQ worker: rq worker durable-monty
3. Run: uv sync --extra rq && uv run python examples/with_rq.py

Note: Functions must be importable by RQ workers. We import them from the module
(not __main__) so they have the correct __module__ attribute for RQ to find them.
"""
import logging
import time
import threading
from durable_monty import init_db, OrchestratorService, Worker
from durable_monty.executors.rq import RQExecutor

# Configure logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# Define functions that RQ workers can import
def add(a, b):
    time.sleep(2)
    return a + b


def multiply(a, b):
    time.sleep(2)
    return a * b


code = """
from asyncio import gather
results = await gather(add(1, 2), add(3, 4), multiply(5, 6))
results += [await add(5, 7)]
results += await gather(add(1, 2), add(3, 4), multiply(5, 6))
sum(results)
"""

if __name__ == "__main__":
    service = OrchestratorService(init_db("sqlite:///rq.db"))

    try:
        executor = RQExecutor()
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        logger.error("Make sure Redis is running: redis-server")
        exit(1)

    # Schedule execution - pass function objects
    exec_id = service.start_execution(code, [add, multiply])
    logger.info(f"Scheduled execution: {exec_id[:8]}...")

    # Run worker
    worker = Worker(service, executor, poll_interval=0.1)
    logger.info("Starting worker (will run until execution completes)...")

    worker.run(until_complete=True)

    # Check result
    result = service.poll(exec_id)
    logger.info(f"Execution {result['status']}: output = {result['output']}")
    if result["status"] != "completed":
        logger.warning("Note: Start RQ workers with: rq worker durable-monty")
