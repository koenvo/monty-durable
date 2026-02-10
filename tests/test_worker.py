"""Test worker integration."""

from durable_monty import init_db, OrchestratorService, Worker, LocalExecutor, register_function


@register_function("add")
def add(a, b):
    return a + b


def test_worker_integration():
    """Test Worker processes execution end-to-end."""
    code = """
from asyncio import gather
results = await gather(add(1, 2), add(3, 4))
sum(results)
"""

    service = OrchestratorService(init_db("sqlite:///:memory:"))
    executor = LocalExecutor()
    worker = Worker(service, executor)

    exec_id = service.start_execution(code, ["add"])

    # Run worker iterations until complete
    for _ in range(10):
        worker.run(once=True)

    result = service.poll(exec_id)
    assert result['status'] == 'completed'
    assert result['output'] == 10


def test_worker_stop_with_threading():
    """Test that worker can be stopped cleanly and responsively when running in a thread."""
    import threading
    import time

    code = """
from asyncio import gather
results = await gather(add(1, 2), add(3, 4))
sum(results)
"""

    service = OrchestratorService(init_db("sqlite:///:memory:"))
    # Use a longer poll interval to verify stop is responsive
    worker = Worker(service, LocalExecutor(), poll_interval=10.0)

    # Create some executions
    for _ in range(3):
        service.start_execution(code, ["add"])

    # Start worker in a thread
    worker_thread = threading.Thread(target=worker.run)
    worker_thread.start()

    # Let it process for a bit
    time.sleep(0.2)

    # Stop the worker
    stop_time = time.time()
    worker.stop()

    # Thread should stop quickly (much less than poll_interval)
    worker_thread.join(timeout=2.0)
    elapsed = time.time() - stop_time

    assert not worker_thread.is_alive(), "Worker thread should have stopped"
    assert elapsed < 2.0, f"Worker took {elapsed}s to stop (should be responsive, not wait for full poll_interval)"


def test_poll_only_returns_waiting_executions():
    """Test that poll() without arguments only returns waiting executions, not completed ones."""
    code = """
from asyncio import gather
results = await gather(add(1, 2), add(3, 4))
sum(results)
"""

    service = OrchestratorService(init_db("sqlite:///:memory:"))

    # Create first execution and complete it
    exec_id_1 = service.start_execution(code, ["add"])
    worker = Worker(service, LocalExecutor())
    for _ in range(10):
        worker.run(once=True)

    # Verify exec_id_1 is completed
    result1 = service.poll(exec_id_1)
    assert result1['status'] == 'completed'

    # Now create more executions
    exec_id_2 = service.start_execution(code, ["add"])
    exec_id_3 = service.start_execution(code, ["add"])

    # Start exec_id_2 but don't complete it
    service.process_execution(exec_id_2)

    # poll() without arguments should only return waiting executions
    all_results = service.poll()
    assert isinstance(all_results, list)

    # Extract all execution IDs from poll results
    polled_exec_ids = [r['execution_id'] for r in all_results]

    # The completed execution (exec_id_1) should NOT be in the results
    assert exec_id_1 not in polled_exec_ids, "Completed execution should not be returned by poll()"

    # The waiting execution (exec_id_2) should be in the results
    assert exec_id_2 in polled_exec_ids, "Waiting execution should be returned"

    # The scheduled execution (exec_id_3) should NOT be in the results
    # (poll only returns "waiting", not "scheduled")
    assert exec_id_3 not in polled_exec_ids, "Scheduled execution should not be returned by poll()"
