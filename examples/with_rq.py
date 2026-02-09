"""Distributed execution with Redis Queue.

Setup:
1. Start Redis: redis-server
2. Start RQ worker: rq worker durable-monty
3. Run: uv sync --extra rq && uv run python examples/with_rq.py
"""

import time
import threading
from durable_monty import init_db, OrchestratorService, Worker, register_function
from durable_monty.executors.rq import RQExecutor


@register_function("add")
def add(a, b):
    return a + b


@register_function("multiply")
def multiply(a, b):
    return a * b


code = """
from asyncio import gather
results = await gather(add(1, 2), add(3, 4), multiply(5, 6))
sum(results)
"""

if __name__ == "__main__":
    service = OrchestratorService(init_db("sqlite:///rq.db"))

    try:
        executor = RQExecutor()
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure Redis is running: redis-server")
        exit(1)

    # Schedule execution
    exec_id = service.start_execution(code, ["add", "multiply"])
    print(f"Scheduled: {exec_id[:8]}...")

    # Run worker
    worker = Worker(service, executor)

    def run_worker():
        for _ in range(20):
            worker.run(once=True)
            time.sleep(0.5)

    thread = threading.Thread(target=run_worker)
    thread.start()
    thread.join()

    # Check result
    result = service.poll(exec_id)
    print(f"Status: {result['status']}, Output: {result['output']}")
    if result["status"] != "completed":
        print("Note: Start RQ workers with: rq worker durable-monty")
