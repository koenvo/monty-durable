"""Core workflow tests."""

from durable_monty import init_db, OrchestratorService, register_function
from durable_monty.functions import execute_function


@register_function("add")
def add(a, b):
    return a + b


def test_full_workflow():
    """Test complete workflow: schedule → start → execute → resume → complete."""
    code = """
from asyncio import gather
results = await gather(add(1, 2), add(3, 4))
sum(results)
"""
    service = OrchestratorService(init_db("sqlite:///:memory:"))

    # Schedule and start
    exec_id = service.start_execution(code, ["add"])
    service.process_execution(exec_id)

    # Check pending calls created
    result = service.poll(exec_id)
    assert result["status"] == "pending"
    assert len(result["pending_calls"]) == 2

    # Execute calls
    for call in service.get_pending_calls(exec_id):
        value = execute_function(call["function_name"], call["args"])
        service.complete_call(exec_id, call["call_id"], value)

    # Verify completed
    result = service.poll(exec_id)
    assert result["status"] == "completed"
    assert result["output"] == 10


def test_execution_with_inputs():
    """Test workflow execution with inputs parameter."""
    code = """
from asyncio import gather
# x and y should be available as direct variables from inputs
results = await gather(add(x, 1), add(y, 2))
sum(results)
"""
    service = OrchestratorService(init_db("sqlite:///:memory:"))

    # Schedule with inputs
    exec_id = service.start_execution(code, ["add"], inputs={"x": 5, "y": 10})
    service.process_execution(exec_id)

    # Check pending calls were created with correct args
    result = service.poll(exec_id)
    assert result["status"] == "pending"
    assert len(result["pending_calls"]) == 2

    # Execute calls
    for call in service.get_pending_calls(exec_id):
        value = execute_function(call["function_name"], call["args"])
        service.complete_call(exec_id, call["call_id"], value)

    # Verify completed (add(5, 1) + add(10, 2) = 6 + 12 = 18)
    result = service.poll(exec_id)
    assert result["status"] == "completed"
    assert result["output"] == 18
