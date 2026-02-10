"""Test executor interface."""

from durable_monty import LocalExecutor


def add(a, b):
    return a + b


def test_local_executor():
    """Test LocalExecutor submit and check."""
    executor = LocalExecutor()

    # Submit call with full path
    job_id = executor.submit_call("tests.test_executor.add", [2, 3])
    assert job_id is not None

    # Check job
    result = executor.check_job(job_id)
    assert result["status"] == "finished"
    assert result["result"] == 5

    # Stats
    stats = executor.get_stats()
    assert stats["executed"] == 1
    assert stats["failed"] == 0


def test_local_executor_error():
    """Test LocalExecutor handles errors."""
    executor = LocalExecutor()

    job_id = executor.submit_call("nonexistent", [1, 2])
    result = executor.check_job(job_id)

    assert result["status"] == "failed"
    assert "error" in result

    stats = executor.get_stats()
    assert stats["failed"] == 1
