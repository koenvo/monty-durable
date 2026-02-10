"""RQ worker task functions."""

import logging
from typing import Any

from durable_monty.functions import execute_function

logger = logging.getLogger(__name__)


def execute_call_task(function_name: str, args: list, kwargs: dict | None = None) -> Any:
    """
    RQ worker task: Execute a function and return result.

    This runs in an RQ worker process. No database access needed.
    """
    kwargs_str = f", {kwargs}" if kwargs else ""
    logger.info(f"RQ worker executing {function_name}{tuple(args)}{kwargs_str}")

    try:
        # Execute the function
        result = execute_function(function_name, args, kwargs)

        logger.info(f"RQ worker completed {function_name}{tuple(args)}{kwargs_str} = {result}")

        return result

    except Exception as e:
        logger.error(f"RQ worker failed: {e}")
        raise
