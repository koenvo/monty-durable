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
