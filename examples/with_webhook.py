"""Event-driven execution with webhook callbacks.

Run: uv sync --extra api && uv run python examples/with_webhook.py
"""

import time
import threading
import httpx
import uvicorn
from durable_monty import init_db, OrchestratorService, Worker, register_function
from durable_monty.api import create_app
from durable_monty.executor import Executor


@register_function("add")
def add(a, b):
    return a + b


class WebhookExecutor(Executor):
    """Simulates event-driven executor (Lambda, Modal) that pushes results via webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def submit_call(self, function_name: str, args: list) -> str:
        import uuid
        from durable_monty.functions import execute_function

        job_id = str(uuid.uuid4())

        def execute_and_callback():
            time.sleep(0.1)
            result = execute_function(function_name, args)
            with httpx.Client() as client:
                client.post(
                    f"{self.webhook_url}/webhook/complete",
                    json={"job_id": job_id, "result": result, "status": "finished"}
                )

        threading.Thread(target=execute_and_callback).start()
        return job_id

    def check_job(self, job_id: str) -> dict:
        return {"status": "submitted"}

    def get_stats(self) -> dict:
        return {}


code = """
from asyncio import gather
results = await gather(add(i, 2), add(3, 4), add(i, 6))
sum(results)
"""

if __name__ == "__main__":
    service = OrchestratorService(init_db("sqlite:///webhook.db"))

    # Start webhook server in background
    app = create_app(service)
    server_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error"),
        daemon=True
    )
    server_thread.start()
    time.sleep(0.5)

    # Schedule and run
    exec_id = service.start_execution(code, ["add"], inputs={"i": 10})

    executor = WebhookExecutor("http://127.0.0.1:8000")
    worker = Worker(service, executor)

    def run_worker():
        for _ in range(30):
            worker.run(once=True)
            time.sleep(0.1)

    thread = threading.Thread(target=run_worker)
    thread.start()
    thread.join()

    result = service.poll(exec_id)
    print(f"Status: {result['status']}, Output: {result['output']}")
