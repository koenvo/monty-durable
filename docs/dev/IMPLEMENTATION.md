# Implementation Guide

This guide walks through implementing a POC of durable-monty step by step.

## Project Structure

```
durable-monty/
├── README.md
├── ARCHITECTURE.md
├── IMPLEMENTATION.md (this file)
├── pyproject.toml
├── durable_monty/
│   ├── __init__.py
│   ├── models.py          # SQLAlchemy models
│   ├── orchestrator.py    # Start/resume execution logic
│   ├── worker.py          # RQ worker wrapper
│   ├── functions.py       # Function registry
│   └── db.py              # Database setup
├── examples/
│   ├── simple_parallel.py
│   └── video_encoding.py
├── tests/
│   └── test_basic.py
└── scripts/
    └── run_worker.py
```

## Step 1: Database Models (models.py)

Create SQLAlchemy models that work with SQLite, Postgres, and MySQL.

**Key requirements:**
- Use `String(36)` for UUIDs (not native UUID type - not in SQLite)
- Use `Text` for JSON (not native JSON type - not in SQLite)
- Use `LargeBinary` for state bytes
- Helper functions `to_json()` and `from_json()` for JSON handling

**Models:**
- `Execution` - workflow execution state
- `Call` - individual external function calls

**Relationships:**
- One execution has many calls
- Cascade delete: deleting execution deletes its calls

**Indexes:**
- `(resume_group_id, status)` for fast "is group complete?" queries

See README.md "Database Schema (SQLAlchemy)" section for full code.

## Step 2: Database Setup (db.py)

**Functionality:**
- `init_db(connection_string)` - create tables, return engine
- `get_session(engine)` - get SQLAlchemy session
- Support multiple databases via connection string

**Examples:**
```python
# SQLite (development)
engine = init_db('sqlite:///durable.db')

# Postgres (production)
engine = init_db('postgresql://user:pass@localhost/dbname')

# MySQL (if needed)
engine = init_db('mysql+pymysql://user:pass@localhost/dbname')
```

## Step 3: Function Registry (functions.py)

Map function names to actual Python implementations.

```python
# functions.py
FUNCTION_REGISTRY = {}

def register_function(name: str):
    """Decorator to register a function."""
    def decorator(func):
        FUNCTION_REGISTRY[name] = func
        return func
    return decorator

# Example usage:
@register_function('encode_video')
def encode_video(filepath: str, quality: str = '1080p'):
    # Actual implementation
    import time
    time.sleep(2)  # Simulate encoding
    return f"encoded_{filepath}"

@register_function('create_playlist')
def create_playlist(videos: list[str]):
    return {'playlist': videos, 'count': len(videos)}
```

**Why?** The worker needs to call the actual Python function based on the function name stored in the database.

## Step 4: Orchestrator (orchestrator.py)

### 4.1: start_execution()

**Input:**
- `session`: SQLAlchemy session
- `code`: Python code string
- `inputs`: dict of input variables
- `external_functions`: list of function names

**Process:**
1. Create Monty instance
2. Call `m.start(inputs=inputs)`
3. Collect all `MontySnapshot` and mark as futures
4. When get `MontyFutureSnapshot`:
   - Generate `resume_group_id`
   - Save `Execution` to DB
   - Save all `Call` records
   - Enqueue tasks to RQ
5. Return `execution_id`

**Edge case:** If execution completes immediately (no external calls), save as 'completed'.

### 4.2: resume_execution()

**Input:**
- `session`: SQLAlchemy session
- `execution_id`: UUID string
- `resume_group_id`: UUID string

**Process:**
1. Load execution state from DB
2. Load all results for `resume_group_id`
3. Deserialize: `MontyFutureSnapshot.load(state)`
4. Resume: `progress.resume(results={call_id: {'return_value': result}, ...})`
5. Handle result:
   - `MontyComplete` → save output, mark completed
   - `MontySnapshot` → mark as future, continue
   - `MontyFutureSnapshot` → new resume group, enqueue tasks

**Important:** Must handle nested `gather()` - create new resume group and repeat process.

## Step 5: Worker Wrapper (worker.py)

### 5.1: enqueue_calls()

Enqueue all calls from a `MontyFutureSnapshot` to RQ.

```python
from redis import Redis
from rq import Queue

redis_conn = Redis()
task_queue = Queue('durable-tasks', connection=redis_conn)

def enqueue_calls(execution_id, resume_group_id, pending_calls):
    for call_id, call_info in pending_calls.items():
        task_queue.enqueue(
            execute_and_save,
            execution_id=execution_id,
            resume_group_id=resume_group_id,
            call_id=call_id,
            function_name=call_info['function'],
            args=call_info['args']
        )
```

### 5.2: execute_and_save()

The wrapper function that runs in RQ worker.

```python
def execute_and_save(execution_id, resume_group_id, call_id, function_name, args):
    """
    Wrapper that:
    1. Executes the actual function
    2. Saves result to DB
    3. Checks if resume group is complete
    4. Triggers resume if ready
    """
    try:
        # Execute actual function
        func = FUNCTION_REGISTRY[function_name]
        result = func(*args)

        # Save result
        with Session(engine) as session:
            call = session.query(Call).filter_by(
                execution_id=execution_id,
                call_id=call_id
            ).first()
            call.status = 'completed'
            call.result = to_json(result)
            call.completed_at = datetime.utcnow()
            session.commit()

        # Check if we should resume
        check_and_resume_if_ready(execution_id, resume_group_id)

    except Exception as e:
        # Save error
        with Session(engine) as session:
            call = session.query(Call).filter_by(
                execution_id=execution_id,
                call_id=call_id
            ).first()
            call.status = 'failed'
            call.error = str(e)
            call.completed_at = datetime.utcnow()
            session.commit()
```

### 5.3: check_and_resume_if_ready()

Check if all calls in resume group are complete. If yes, trigger resume.

```python
def check_and_resume_if_ready(execution_id, resume_group_id):
    with Session(engine) as session:
        # Count calls
        from sqlalchemy import func
        result = session.query(
            func.count(Call.id).label('total'),
            func.count(Call.id).filter(Call.status == 'completed').label('completed'),
            func.count(Call.id).filter(Call.status == 'failed').label('failed')
        ).filter(
            Call.resume_group_id == resume_group_id
        ).first()

        total = result.total
        completed = result.completed
        failed = result.failed

        # All done?
        if total == completed + failed:
            if failed > 0:
                # Mark execution as failed
                execution = session.query(Execution).filter_by(id=execution_id).first()
                execution.status = 'failed'
                session.commit()
                return

            # All completed - check if we should resume
            execution = session.query(Execution).filter_by(id=execution_id).first()
            if execution.status == 'waiting':
                # Prevent double-resume
                execution.status = 'resuming'
                session.commit()

                # Resume (outside transaction)
                resume_execution(session, execution_id, resume_group_id)
```

## Step 6: Example Usage

### Simple Example

```python
# examples/simple_parallel.py
from durable_monty import start_execution, init_db
from durable_monty.functions import register_function
from sqlalchemy.orm import Session

# Register functions
@register_function('add')
def add(a, b):
    return a + b

@register_function('multiply')
def multiply(a, b):
    return a * b

# Code to execute
code = """
from asyncio import gather

async def workflow():
    results = await gather(
        add(1, 2),
        add(3, 4),
        multiply(5, 6)
    )
    return sum(results)

await workflow()
"""

# Initialize DB
engine = init_db('sqlite:///example.db')

# Start execution
with Session(engine) as session:
    execution_id = start_execution(
        session=session,
        code=code,
        inputs={},
        external_functions=['add', 'multiply']
    )

print(f"Started execution: {execution_id}")
# Now RQ workers will execute the tasks
# When all complete, execution will resume automatically
```

### Video Encoding Example

See README.md for the TeamTV video encoding example.

## Step 7: Running the System

### Start Redis

```bash
redis-server
```

### Start RQ Worker(s)

```bash
# Terminal 1
rq worker durable-tasks

# Terminal 2 (optional - more workers)
rq worker durable-tasks
```

### Run Your Application

```python
from durable_monty import start_execution, init_db
from sqlalchemy.orm import Session

engine = init_db('sqlite:///app.db')

with Session(engine) as session:
    execution_id = start_execution(
        session=session,
        code=my_workflow_code,
        inputs={'video_files': ['a.mp4', 'b.mp4']},
        external_functions=['encode_video', 'create_playlist']
    )
```

### Query Status

```python
from durable_monty.models import Execution

with Session(engine) as session:
    execution = session.query(Execution).filter_by(id=execution_id).first()
    print(f"Status: {execution.status}")
    if execution.status == 'completed':
        print(f"Output: {from_json(execution.output)}")
```

## Step 8: Testing

### Unit Tests

Test each component:
- Models (create, query, relationships)
- Orchestrator (start, resume)
- Worker wrapper
- Function registry

### Integration Test

End-to-end test:
1. Start execution
2. RQ workers execute tasks
3. Verify execution completes
4. Check output is correct

```python
import pytest
from durable_monty import start_execution, init_db
from durable_monty.functions import register_function

@register_function('test_add')
def test_add(a, b):
    return a + b

def test_simple_workflow():
    code = """
from asyncio import gather
results = await gather(test_add(1, 2), test_add(3, 4))
sum(results)
"""

    engine = init_db('sqlite:///:memory:')
    session = Session(engine)

    execution_id = start_execution(
        session, code, {}, ['test_add']
    )

    # Wait for completion (in real test, would poll or use callback)
    # For now, manually trigger resume
    # ...

    execution = session.query(Execution).filter_by(id=execution_id).first()
    assert execution.status == 'completed'
    assert from_json(execution.output) == 10
```

## Step 9: Error Handling (TODO)

### Task Failures

- Retry with exponential backoff
- Max retry count
- Dead letter queue for permanently failed tasks

### Resume Failures

- Don't retry automatically (could loop)
- Log error
- Mark execution as failed
- Store error details

### Validation

- Validate code before execution (type check with Monty)
- Validate function names exist in registry
- Validate inputs match expected types

## Step 10: Monitoring (TODO)

### Metrics

- Execution counts (started, completed, failed)
- Task counts (pending, running, completed)
- Resume latency (time from last task done → resume complete)
- Task execution time

### Logging

- Execution lifecycle events
- Task execution start/complete
- Resume triggers
- Errors

### Dashboard

- RQ dashboard for task queue
- Custom dashboard for executions
  - List executions
  - View status
  - View output
  - View call tree

## Next Steps

1. Implement basic orchestrator + worker
2. Add simple example
3. Test with RQ
4. Add error handling
5. Add retry logic
6. Add monitoring
7. Add API layer (FastAPI?)
8. Add execution query/management endpoints

## Implementation Checklist

- [ ] Database models (models.py)
- [ ] Database setup (db.py)
- [ ] Function registry (functions.py)
- [ ] Orchestrator start_execution (orchestrator.py)
- [ ] Orchestrator resume_execution (orchestrator.py)
- [ ] Worker wrapper enqueue_calls (worker.py)
- [ ] Worker wrapper execute_and_save (worker.py)
- [ ] Worker wrapper check_and_resume_if_ready (worker.py)
- [ ] Simple example (examples/simple_parallel.py)
- [ ] Video encoding example (examples/video_encoding.py)
- [ ] Basic tests (tests/test_basic.py)
- [ ] RQ worker script (scripts/run_worker.py)
- [ ] Package setup (pyproject.toml)
- [ ] Documentation (README.md, ARCHITECTURE.md)

## Tips for Implementation

1. **Start with SQLite** - easier to develop and test
2. **Test each component separately** - don't try to build everything at once
3. **Use in-memory SQLite for tests** - fast, no cleanup needed
4. **Mock RQ for unit tests** - test logic without Redis dependency
5. **Handle nested gather early** - it's trickier than it looks
6. **Log everything** - makes debugging much easier
7. **Keep it simple** - get basic version working before adding features