"""Function execution via dynamic import."""

from typing import Callable, Any
import importlib


def get_function(path: str) -> Callable:
    """
    Get a function by its full import path via dynamic import.

    Args:
        path: Full import path like "myapp.tasks.process" or "__main__.add"

    Returns:
        The function object

    Raises:
        KeyError: If function cannot be imported
    """
    # Check if path has at least one dot (module.function format)
    if "." not in path:
        raise KeyError(
            f"Invalid function path '{path}'. "
            f"Must be a full import path like 'myapp.tasks.{path}' or '__main__.{path}'."
        )

    # Dynamic import
    try:
        module_path, func_name = path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        raise KeyError(
            f"Could not import function '{path}'. "
            f"Make sure the module exists and the function is defined. Error: {e}"
        )


def execute_function(path: str, args: list, kwargs: dict | None = None) -> Any:
    """
    Execute a function by its full import path.

    Args:
        path: Full import path like "myapp.tasks.process"
        args: Positional arguments
        kwargs: Keyword arguments

    Returns:
        Function result
    """
    func = get_function(path)
    return func(*args, **(kwargs or {}))
