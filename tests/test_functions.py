"""Test function dynamic import."""

from durable_monty.functions import execute_function, get_function
import pytest


def test_execute_stdlib_function():
    """Test executing standard library functions via dynamic import."""
    result = execute_function("os.path.join", ["a", "b"])
    assert result == "a/b"


def test_execute_with_kwargs():
    """Test executing functions with keyword arguments."""
    # Test with proper module function
    result = execute_function("os.path.join", ["a", "b", "c"])
    assert result == "a/b/c"


def test_get_function_error_no_dot():
    """Test that get_function raises error for paths without dots."""
    with pytest.raises(KeyError) as exc_info:
        get_function("add")
    assert "Invalid function path" in str(exc_info.value)
    assert "__main__.add" in str(exc_info.value)


def test_get_function_error_import_failed():
    """Test that get_function raises error for non-existent modules."""
    with pytest.raises(KeyError) as exc_info:
        get_function("nonexistent.module.func")
    assert "Could not import" in str(exc_info.value)
