# Durable Monty

**Durable functions for Python.** Write normal `async/await` code that pauses at `gather()`, executes tasks in parallel (even distributed), and resumes when done.

## What Are Durable Functions?

Durable functions are workflows that survive crashes and restarts. Your code pauses when waiting for tasks, saves its state to a database, and resumes exactly where it left off when tasks complete - even if your process dies in between.

**Perfect for:** Long-running workflows, parallel task execution, distributed systems, background jobs.

## How It Works

Powered by [monty-python](https://github.com/lix-tech/pydantic-monty) - a sandboxed Python interpreter that can pause and serialize execution state. When your code hits `await gather()`, Monty captures the exact execution state (~800 bytes), returns pending tasks, and later resumes from that exact point with results.

**Result:** Pure Python async/await that works like Temporal or AWS Step Functions, but simpler.

```python
from durable_monty import init_db, OrchestratorService, Worker, register_function, LocalExecutor

@register_function("process")
def process(item):
    return f"processed_{item}"

code = """
from asyncio import gather
results = await gather(
    process('a'),
    process('b'),
    process('c')
)
results
"""

service = OrchestratorService(init_db())
exec_id = service.start_execution(code, ["process"])

worker = Worker(service, LocalExecutor())
worker.run()
```

Output: `['processed_a', 'processed_b', 'processed_c']`

## Install

```bash
uv add durable-monty
```

## How It Works

1. Code hits `gather()` → pauses and saves state (~800 bytes)
2. Creates pending calls in database
3. Worker picks them up and executes in parallel
4. When all complete → resumes and returns result

State survives restarts. Parallel execution. Pure Python.

## Distributed Execution

**Redis Queue:**
```bash
uv add durable-monty --extra rq
```

```python
from durable_monty.executors.rq import RQExecutor

worker = Worker(service, RQExecutor())
worker.run()

# Start RQ workers: rq worker durable-monty
```

**Event-driven (Lambda, Modal):**
```bash
uv add durable-monty --extra api
```

```python
from durable_monty.api import create_app
import uvicorn

app = create_app(service)
uvicorn.run(app, port=8000)

# Executors POST results to: /webhook/complete
```

## Examples

- `examples/with_worker.py` - Local execution
- `examples/with_rq.py` - Redis Queue
- `examples/with_webhook.py` - Webhooks

## Development

```bash
git clone https://github.com/koenvo/monty-durable
cd monty-durable
uv sync
uv run pytest
```

## License

MIT
