# Getting Started

Welcome! This guide will help you start implementing durable-monty.

## Quick Context

**What is this?** A durable functions framework using monty-python that lets you write normal Python async/await code that can pause, persist state, execute tasks in parallel, and resume later.

**Example:**
```python
# This code can pause at the gather(), save state, execute videos in parallel,
# and resume when all are done - even if the process restarts!
results = await gather(
    encode_video('a.mp4'),
    encode_video('b.mp4'),
    encode_video('c.mp4')
)
```

## Read These First

1. **README.md** - Concept, architecture, comparisons (~15 min read)
2. **ARCHITECTURE.md** - How it works, data flow (~10 min read)
3. **IMPLEMENTATION.md** - Step-by-step implementation guide (~20 min read)
4. **PROJECT_PLAN.md** - Task breakdown and timeline (~10 min read)

**Total:** ~1 hour to understand the full project

## Quick Start

If you're ready to start coding immediately:

### 1. Create Project Structure

```bash
mkdir -p durable_monty/{tests,examples,scripts}
touch durable_monty/__init__.py
touch durable_monty/{models,db,orchestrator,worker,functions}.py
touch examples/{simple_parallel,video_encoding}.py
touch tests/test_basic.py
```

### 2. Create pyproject.toml

```toml
[project]
name = "durable-monty"
version = "0.1.0"
description = "Durable functions using monty-python"
requires-python = ">=3.10"
dependencies = [
    "pydantic-monty>=0.1.0",
    "sqlalchemy>=2.0.0",
    "rq>=1.15.0",
    "redis>=5.0.0",
]

[project.optional-dependencies]
postgres = ["psycopg[binary]>=3.1.0"]
dev = ["pytest>=7.0.0", "black>=23.0.0", "ruff>=0.1.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 3. Start with Models

**File:** `durable_monty/models.py`

Copy the SQLAlchemy models from README.md "Database Schema (SQLAlchemy)" section.

**Key points:**
- Use `String(36)` for UUIDs
- Use `Text` for JSON (with helper functions)
- Use `LargeBinary` for state
- Add proper relationships and indexes

### 4. Test the Models

```python
# Test it works
from durable_monty.models import init_db, Execution, Call
from sqlalchemy.orm import Session

engine = init_db('sqlite:///test.db')
session = Session(engine)

# Create an execution
exec = Execution(
    id='test-123',
    code='print("hello")',
    status='waiting'
)
session.add(exec)
session.commit()

# Query it back
result = session.query(Execution).first()
print(result.id)  # Should print: test-123
```

### 5. Implement in This Order

Follow PROJECT_PLAN.md tasks:

1. **Models + DB** (Day 1)
   - `models.py` - SQLAlchemy models
   - `db.py` - Database setup
   - Test with SQLite

2. **Function Registry** (Day 2)
   - `functions.py` - Function registration
   - Add example functions
   - Test function calls

3. **Orchestrator** (Day 3-4)
   - `orchestrator.py` - start_execution()
   - `orchestrator.py` - resume_execution()
   - Test with mocked dependencies

4. **Worker** (Day 4-5)
   - `worker.py` - RQ integration
   - `worker.py` - execute_and_save()
   - `worker.py` - check_and_resume_if_ready()
   - Test with real RQ

5. **Examples** (Day 5)
   - `examples/simple_parallel.py`
   - `examples/video_encoding.py`
   - End-to-end test

## Key Concepts to Understand

### Resume Group ID

Every `gather()` creates a group of calls. They all share a `resume_group_id`. We only resume when ALL calls in the group are done.

```python
# One resume group (abc123) with 3 calls
results = await gather(
    task1(),  # call_id=0, resume_group_id=abc123
    task2(),  # call_id=1, resume_group_id=abc123
    task3()   # call_id=2, resume_group_id=abc123
)
```

### State Serialization

Monty snapshots are small (~800 bytes) and contain:
- Stack frames
- Local variables
- Execution position

NOT the code or large data - those are stored separately.

### Worker Wrapper Pattern

```python
def execute_and_save(...):
    result = actual_function(...)  # Do work
    save_to_db(result)             # Persist
    check_and_resume_if_ready()   # Trigger resume if group done
```

This ensures results are saved and resume is triggered automatically.

## Testing Strategy

### Unit Tests

Test each component in isolation:
- Models: create, query, relationships
- Orchestrator: start, resume (mock DB/RQ)
- Worker: execute, save (mock DB)

### Integration Tests

Test end-to-end:
- Start execution → workers execute → resume → complete
- Use in-memory SQLite for speed
- Mock or use real Redis/RQ

### Manual Testing

1. Start Redis: `redis-server`
2. Start worker: `rq worker durable-tasks`
3. Run example: `python examples/simple_parallel.py`
4. Check database: `sqlite3 durable.db "SELECT * FROM executions"`

## Common Pitfalls

### 1. UUID Type Issues

**Problem:** SQLite doesn't have native UUID type
**Solution:** Use `String(36)` and store as string

### 2. JSON Type Issues

**Problem:** SQLite doesn't have native JSON type
**Solution:** Use `Text` + `to_json()`/`from_json()` helpers

### 3. Double Resume

**Problem:** Multiple workers complete at same time, try to resume
**Solution:** Use transaction + status check (`waiting` → `resuming`)

### 4. Nested Gather

**Problem:** Workflow has multiple `gather()` calls
**Solution:** Each creates new resume_group_id, handled recursively

### 5. Function Not Found

**Problem:** Worker can't find function in registry
**Solution:** Ensure all functions are registered before starting workers

## Development Workflow

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black durable_monty/
ruff check durable_monty/

# Start Redis (in terminal 1)
redis-server

# Start worker (in terminal 2)
rq worker durable-tasks

# Run example (in terminal 3)
python examples/simple_parallel.py

# Check results
sqlite3 durable.db "SELECT id, status, output FROM executions"
```

## Next Steps

1. **Read all docs** (if you haven't already)
2. **Set up project** (create files, install deps)
3. **Start with models** (easiest, foundational)
4. **Work through phases** (follow PROJECT_PLAN.md)
5. **Test incrementally** (don't build everything at once)
6. **Ask questions** (if stuck, refer to docs or ask user)

## Need Help?

- Check IMPLEMENTATION.md for detailed code examples
- Check ARCHITECTURE.md for how things fit together
- Check README.md for the big picture and comparisons
- Check PROJECT_PLAN.md for task breakdown

## Success Criteria

You'll know you're done with MVP when:

✅ Can run `python examples/simple_parallel.py`
✅ See tasks executing in RQ worker logs
✅ Execution completes with correct result
✅ Database contains execution state and results
✅ Tests pass

Good luck! 🚀