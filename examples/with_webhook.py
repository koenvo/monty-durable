"""Example showing event-driven execution with webhook callbacks.

This demonstrates how executors can push results via webhook instead of being polled.
Useful for AWS Lambda, Modal, or other event-driven compute platforms.

To run this:
1. uv sync --extra api  # Install FastAPI dependencies
2. uv run python examples/with_webhook.py
"""

import logging
import time
import threading
import httpx
from durable_monty import init_db, OrchestratorService, Worker, register_function, create_app
from durable_monty.executor import Executor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Register functions
@register_function("add")
def add(a, b):
    return a + b


@register_function("multiply")
def multiply(a, b):
    return a * b


class WebhookExecutor(Executor):
    """
    Simulated event-driven executor that pushes results via webhook.

    In production, this would be AWS Lambda, Modal, etc. calling the webhook
    when the function completes.
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.jobs = {}

    def submit_call(self, function_name: str, args: list) -> str:
        """Submit call and trigger async execution with callback."""
        import uuid
        from durable_monty.functions import execute_function

        job_id = str(uuid.uuid4())

        # Simulate async execution - in production this would be Lambda/Modal/etc
        def execute_and_callback():
            time.sleep(0.1)  # Simulate work
            try:
                result = execute_function(function_name, args)

                # Push result to webhook (this is what Lambda would do)
                with httpx.Client() as client:
                    response = client.post(
                        f"{self.webhook_url}/webhook/complete",
                        json={"job_id": job_id, "result": result, "status": "finished"}
                    )
                    logging.info(f"Webhook callback sent for {function_name}: {response.status_code}")

            except Exception as e:
                # Push error to webhook
                with httpx.Client() as client:
                    client.post(
                        f"{self.webhook_url}/webhook/complete",
                        json={"job_id": job_id, "status": "failed", "error": str(e)}
                    )

        # Start background thread (simulating Lambda trigger)
        thread = threading.Thread(target=execute_and_callback)
        thread.start()

        return job_id

    def check_job(self, job_id: str) -> dict:
        """Not used in event-driven mode - webhook pushes results."""
        return {"status": "submitted", "message": "Use webhook for results"}

    def get_stats(self) -> dict:
        return {}


# Workflow code
code = """
from asyncio import gather
results = await gather(
    add(1, 2),
    add(3, 4),
    multiply(5, 6)
)
sum(results)
"""

if __name__ == "__main__":
    # Initialize
    engine = init_db("sqlite:///webhook_example.db")
    service = OrchestratorService(engine)

    # Start FastAPI webhook server
    print("=== Starting webhook server ===")
    app = create_app(service)

    import uvicorn

    # Run server in background thread
    server_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning"),
        daemon=True
    )
    server_thread.start()
    time.sleep(1)  # Wait for server to start
    print("Webhook server running at http://127.0.0.1:8000")
    print("API docs at http://127.0.0.1:8000/docs\n")

    # Schedule execution
    print("=== Scheduling execution ===")
    exec_id = service.start_execution(code, ["add", "multiply"])
    print(f"Scheduled: {exec_id[:8]}...\n")

    # Create webhook executor
    executor = WebhookExecutor(webhook_url="http://127.0.0.1:8000")

    # Run worker (only needs to process scheduled, not poll jobs)
    print("=== Worker processing (event-driven) ===")
    worker = Worker(service, executor, poll_interval=0.1)

    def run_worker():
        for _ in range(30):
            if not worker.running:
                break
            worker._process_scheduled()
            worker._process_pending_calls()
            # Note: No _process_submitted_jobs() needed - webhook handles it!
            worker._process_waiting()
            time.sleep(0.1)

    worker.running = True
    worker_thread = threading.Thread(target=run_worker)
    worker_thread.start()
    worker_thread.join()

    # Check result
    print("\n=== Result ===")
    result = service.poll(exec_id)
    print(f"Status: {result['status']}")
    print(f"Output: {result['output']}")
    print(f"\n✓ Event-driven execution complete!")
    print("  Functions pushed results via webhook (no polling needed)")
