# Durable-Monty

**Durable functions using monty-python** - Write normal Python async/await code that can pause, persist state, execute tasks in parallel, and resume when results are ready.

## Quick Start

```python
from durable_monty import init_db, OrchestratorService, Worker, register_function

# 1. Register functions
@register_function("encode_video")
def encode_video(filepath: str):
    # Your encoding logic
    return f"encoded_{filepath}"

# 2. Define workflow
code = """
from asyncio import gather
results = await gather(
    encode_video('a.mp4'),
    encode_video('b.mp4'),
    encode_video('c.mp4')
)
results
"""

# 3. Start execution
service = OrchestratorService(init_db())
exec_id = service.start_execution(code, ["encode_video"])

# 4. Run worker
from durable_monty import LocalExecutor

executor = LocalExecutor()
worker = Worker(service, executor)
worker.run()  # Processes scheduled executions, executes calls, resumes workflows
```

That's it! Your workflow will:
1. Pause at `gather()` and save state (~800 bytes)
2. Execute all 3 videos in parallel
3. Resume when done and return results

## How It Works

### The Magic of MontyFutureSnapshot

When your code hits `asyncio.gather()`:

```python
results = await gather(
    encode_video('file1.mp4'),
    encode_video('file2.mp4'),
    encode_video('file3.mp4')
)
```

Monty **pauses execution** and returns a `MontyFutureSnapshot` containing:
- Serialized execution state (~800 bytes)
- All pending task IDs that need to be executed
- Everything needed to resume later

**This means:** Save the state to a database, execute tasks on workers (in parallel!), and resume the workflow when results arrive - even hours or days later.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  User                            │
│  service.start_execution(code, functions)        │
└────────────────────┬────────────────────────────┘
                     ↓
              ┌──────────────┐
              │   Database   │
              │  (scheduled) │
              └──────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│               Worker Loop                        │
│  1. Start scheduled executions                   │
│  2. Submit calls to Executor                     │
│  3. Poll job results                             │
│  4. Resume completed workflows                   │
└────────────────────┬────────────────────────────┘
                     ↓
              ┌──────────────┐
              │   Executor   │
              │ (pluggable)  │
              └──────────────┘
         ┌───────┴────────┬────────┐
         ↓                ↓        ↓
    LocalExecutor    RQExecutor  ModalExecutor
```

## Execution Flow

### 1. Schedule Execution

```python
from durable_monty import init_db, OrchestratorService, register_function

@register_function("add")
def add(a, b):
    return a + b

code = """
from asyncio import gather
results = await gather(add(1, 2), add(3, 4))
sum(results)
"""

service = OrchestratorService(init_db("sqlite:///app.db"))
exec_id = service.start_execution(code, ["add"])
# Status: "scheduled" - saved to DB, no execution yet
```

### 2. Worker Processes

```python
from durable_monty import Worker

worker = Worker(service)
worker.run()

# Worker loop:
# 1. Pick up scheduled execution → start with Monty → create calls
# 2. Submit calls to executor → store job_id
# 3. Poll job results → update when complete
# 4. Resume workflow when all calls done
```

### 3. Pluggable Executors

**Local (same process):**
```python
from durable_monty import LocalExecutor

executor = LocalExecutor()
worker = Worker(service, executor)
worker.run()
```

**Redis Queue (distributed):**
```python
from durable_monty.executors.rq import RQExecutor

executor = RQExecutor(queue_name="my-queue")
worker = Worker(service, executor)
worker.run()

# Start RQ workers: rq worker my-queue
```

**Event-driven with webhooks (AWS Lambda, Modal, etc.):**
```python
from durable_monty import create_app
import uvicorn

# Start webhook server
app = create_app(service)
uvicorn.run(app, host="0.0.0.0", port=8000)

# Your executor pushes results to: POST /webhook/complete
# { "job_id": "...", "result": ..., "status": "finished" }
```

**Custom (Modal, Lambda, etc.):**
```python
from durable_monty.executor import Executor

class ModalExecutor(Executor):
    def submit_call(self, call):
        # Submit to Modal, store job_id
        ...

    def check_job(self, job_id):
        # Check job status, return result
        ...
```

See [EXECUTORS.md](docs/EXECUTORS.md) for details.

## Key Features

### ✅ Pure Python Async/Await

No decorators, no special SDK. Just write normal Python:

```python
from asyncio import gather

# This is the ACTUAL code
results = await gather(
    encode_video('a.mp4'),
    encode_video('b.mp4')
)
```

### ✅ Minimal Infrastructure

- **Development**: SQLite + LocalExecutor (single process)
- **Production**: Postgres + RQExecutor (distributed workers)

No Kafka, no Temporal server, no complex setup.

### ✅ Tiny State Snapshots

~800 bytes per snapshot. Just the execution state:
- Stack frames
- Local variables
- Execution position

NOT included: function code, large data, external function implementations.

### ✅ Sandboxed Execution

Monty is a secure Python sandbox. Workflows can't:
- Access the filesystem
- Make network calls (except through external functions)
- Import arbitrary libraries
- Execute system commands

Safe for **AI-generated** or **untrusted** workflow code.

### ✅ Pluggable Executors

Execute functions anywhere:
- **LocalExecutor** - same process
- **RQExecutor** - Redis Queue (distributed)
- **ModalExecutor** - Modal.com
- **LambdaExecutor** - AWS Lambda

Workers are pure computation - no database access needed!

## Real-World Example: Video Encoding

```python
from durable_monty import init_db, OrchestratorService, Worker, register_function

@register_function("encode_video")
def encode_video(filepath: str, quality: str):
    # Actual encoding - takes hours!
    ...
    return encoded_path

@register_function("generate_thumbnail")
def generate_thumbnail(video_path: str):
    ...
    return thumbnail_path

@register_function("create_package")
def create_package(videos: list, thumbnails: list):
    ...
    return package_url

code = """
from asyncio import gather

async def encode_episode(raw_files):
    # 1. Encode all videos in parallel (takes hours)
    videos = await gather(*[
        encode_video(f, quality='1080p')
        for f in raw_files
    ])

    # 2. Generate thumbnails in parallel
    thumbnails = await gather(*[
        generate_thumbnail(v)
        for v in videos
    ])

    # 3. Create final package
    result = await create_package(videos, thumbnails)

    return result

await encode_episode(input_files)
"""

# Start execution
service = OrchestratorService(init_db())
exec_id = service.start_execution(
    code,
    ["encode_video", "generate_thumbnail", "create_package"],
    inputs={"input_files": ["ep1.mp4", "ep2.mp4", "ep3.mp4"]}
)

# Run workers (can be multiple processes/servers)
from durable_monty.executors.rq import RQExecutor

worker = Worker(service, executor=RQExecutor())
worker.run()
```

**Benefits:**
- ✅ Workflow survives server restarts (state in DB)
- ✅ True parallel execution (all videos encode at once)
- ✅ Clean Python code (no callback hell)
- ✅ Automatic state management (monty handles serialization)
- ✅ Event-driven (resume when tasks complete)

## Installation

```bash
# Basic
pip install durable-monty

# With RQ support
pip install durable-monty[rq]

# With API/webhook support
pip install durable-monty[api]

# With Postgres
pip install durable-monty[postgres]

# All extras
pip install durable-monty[rq,api,postgres]
```

Or with uv:
```bash
uv add durable-monty
uv add durable-monty --extra api  # for webhook support
uv add durable-monty --extra rq   # for RQ executor
```

## API Reference

### OrchestratorService

```python
from durable_monty import init_db, OrchestratorService

engine = init_db("sqlite:///app.db")  # or postgresql://...
service = OrchestratorService(engine)

# Schedule execution
exec_id = service.start_execution(
    code="await add(1, 2)",
    external_functions=["add"],
    inputs=None  # or {"var": value}
)

# Poll specific execution
result = service.poll(exec_id)
# Returns: {"execution_id": str, "status": str, "output": Any, "pending_calls": list}

# Poll all executions
results = service.poll()
# Returns: list of above dicts

# Get pending calls
calls = service.get_pending_calls(exec_id)

# Complete a call
service.complete_call(exec_id, call_id, result)
```

### Worker

```python
from durable_monty import Worker, LocalExecutor
from durable_monty.executors.rq import RQExecutor

# Local execution
executor = LocalExecutor()
worker = Worker(service, executor)

# RQ execution
executor = RQExecutor()
worker = Worker(service, executor)

# Custom executor
executor = MyExecutor()
worker = Worker(service, executor, poll_interval=1.0)

# Run worker loop
worker.run()  # Blocks - processes everything
```

### Register Functions

```python
from durable_monty import register_function

@register_function("my_function")
def my_function(arg1, arg2):
    return result

# Or directly
from durable_monty import FUNCTION_REGISTRY
FUNCTION_REGISTRY["my_function"] = my_function
```

## Comparison with Existing Solutions

### vs. Temporal

**Temporal:**
- ✅ Production-ready, battle-tested
- ❌ Heavy infrastructure (Temporal server, Cassandra/PostgreSQL cluster)
- ❌ Special SDK required (`@workflow.defn`, `workflow.execute_activity`)
- ❌ Complex setup and operational overhead

**Durable-Monty:**
- ✅ **Pure Python async/await** - no special decorators
- ✅ **Minimal infrastructure** - just Postgres
- ✅ **Lightweight** - state snapshots are ~800 bytes
- ✅ **Run anywhere** - no vendor dependencies

### vs. AWS Lambda / Azure Durable Functions

**AWS/Azure:**
- ✅ Serverless, auto-scaling
- ❌ **Vendor lock-in**
- ❌ **Cost** - pay per execution
- ❌ Step Functions syntax instead of pure Python

**Durable-Monty:**
- ✅ **No vendor lock-in**
- ✅ **Cost-effective** - just your server costs
- ✅ **Pure Python**
- ✅ **Pluggable** - run on RQ, Modal, Lambda, etc.

## Development

```bash
# Clone repo
git clone https://github.com/yourusername/durable-monty
cd durable-monty

# Install with uv
uv sync

# Run tests
uv run pytest

# Run examples
uv run python examples/with_worker.py
```

## Examples

See the `examples/` directory:
- `with_worker.py` - Worker-based execution (recommended)
- `with_rq.py` - Distributed execution with RQ
- `with_webhook.py` - Event-driven execution with webhooks
- `simple.py` - Manual execution example
- `poll_all.py` - Polling multiple executions

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - System architecture and data flow
- [EXECUTORS.md](docs/EXECUTORS.md) - Creating custom executors (Modal, Lambda, etc.)

## Why Durable-Monty?

**When to use:**
- You want **full control** over your infrastructure
- You need **lean, minimal** setup (single server + Postgres)
- You want to run **AI-generated** or **untrusted** workflow code safely
- You prefer **pure Python** over framework-specific patterns
- You're building something new and want **flexibility**

**When to use Temporal/AWS/Azure:**
- You need production-ready, battle-tested system **now**
- You have complex error handling/retry requirements
- You need enterprise support
- You're already invested in that ecosystem

## Status

🚧 **Alpha** - Core functionality works, but not production-ready yet. Use for experimentation and prototyping.

**Working:**
- ✅ Basic workflow execution
- ✅ Parallel task execution
- ✅ State persistence and resume
- ✅ Local and RQ executors
- ✅ Nested gather()

**TODO:**
- ⏳ Retry logic and error handling
- ⏳ Monitoring and logging improvements
- ⏳ API layer (FastAPI)
- ⏳ Execution query/management endpoints
- ⏳ Production hardening

## License

MIT
