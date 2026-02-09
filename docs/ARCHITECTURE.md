# Architecture

## Overview

Durable-monty enables durable function execution using monty-python's sandboxed interpreter. Workflows can pause at async boundaries, persist state to a database, execute tasks in parallel via workers, and resume when results are ready.

## Core Components

```
┌─────────────────────────────────────────────┐
│            Client Application                │
│  - Submits workflows                         │
│  - Queries execution status                  │
└──────────────┬──────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────┐
│            Orchestrator                      │
│  - Starts executions                         │
│  - Handles MontyFutureSnapshot               │
│  - Saves state to DB                         │
│  - Enqueues tasks to RQ                      │
│  - Resumes executions when ready             │
└──────────────┬──────────────────────────────┘
               │
               ├─────→ Database (SQLite/Postgres/MySQL)
               │       ├─ executions table
               │       └─ calls table
               │
               └─────→ Redis + RQ
                       └─ Task queue
                            │
                            ↓
               ┌─────────────────────────┐
               │   RQ Workers (1...N)     │
               │  - Pick up tasks         │
               │  - Execute functions     │
               │  - Save results to DB    │
               │  - Check if group done   │
               │  - Trigger resume        │
               └─────────────────────────┘
```

## Data Flow

### 1. Start Execution

```
User → Orchestrator → Monty.start()
                        ↓
                   MontySnapshot (call 1)
                        ↓
                   resume(future=...)
                        ↓
                   MontySnapshot (call 2)
                        ↓
                   resume(future=...)
                        ↓
                   MontyFutureSnapshot
                        ↓
                   Generate resume_group_id
                        ↓
                   Save to DB:
                   - execution (with state)
                   - calls (all pending)
                        ↓
                   Enqueue to RQ:
                   - task 1
                   - task 2
                   - task 3
```

### 2. Execute Tasks (Parallel)

```
RQ Worker 1              RQ Worker 2              RQ Worker 3
    ↓                        ↓                        ↓
execute_and_save()      execute_and_save()      execute_and_save()
    ↓                        ↓                        ↓
encode_video(url1)      encode_video(url2)      encode_video(url3)
    ↓                        ↓                        ↓
Save result to DB       Save result to DB       Save result to DB
    ↓                        ↓                        ↓
Check if group done?    Check if group done?    Check if group done?
(no - 1/3 done)        (no - 2/3 done)        (yes - 3/3 done!)
                                                     ↓
                                              resume_execution()
```

### 3. Resume Execution

```
resume_execution(execution_id, resume_group_id)
    ↓
Load state from DB
    ↓
Load all results for resume_group_id
    ↓
MontyFutureSnapshot.load(state)
    ↓
progress.resume(results={call_id: result, ...})
    ↓
    ├─→ MontyComplete → Save output, mark execution completed
    ├─→ MontySnapshot → Mark as future, continue
    └─→ MontyFutureSnapshot → New resume_group_id, enqueue new tasks
```

## Key Concepts

### Resume Group ID

Every `MontyFutureSnapshot` gets a unique `resume_group_id`. All calls in `pending_call_ids` belong to this group.

**Why?** Because `gather()` batches multiple async calls together - we need to know which calls must complete before we can resume.

```python
# This gather() creates ONE resume group with 3 calls
results = await gather(
    encode_video('a.mp4'),  # call_id=0, resume_group_id=abc123
    encode_video('b.mp4'),  # call_id=1, resume_group_id=abc123
    encode_video('c.mp4')   # call_id=2, resume_group_id=abc123
)
# We can only resume when ALL 3 are done
```

**Nested gather:**
```python
# First gather - resume_group_id=abc123
videos = await gather(encode_video('a.mp4'), encode_video('b.mp4'))

# Second gather - resume_group_id=def456 (NEW group!)
thumbnails = await gather(generate_thumb(videos[0]), generate_thumb(videos[1]))
```

### State Serialization

Monty's state snapshots are **tiny** (~800 bytes):
- Stack frames
- Local variables
- Execution position
- Pending call information

**NOT included:**
- Function code (stored separately in `executions.code`)
- Large data structures (passed as function arguments)
- External function implementations

### Worker Wrapper Pattern

```python
def execute_and_save(execution_id, resume_group_id, call_id, function_name, args):
    """
    Wrapper that:
    1. Executes the actual function
    2. Saves result to DB
    3. Checks if resume group is complete
    4. Triggers resume if ready
    """
    result = FUNCTION_REGISTRY[function_name](*args)
    save_result_to_db(call_id, result)
    check_and_resume_if_ready(execution_id, resume_group_id)
```

This wrapper ensures:
- Results are persisted
- Resume is triggered automatically
- No separate polling needed

## Database Schema

### Executions Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | String(36) | UUID |
| `code` | Text | The monty code |
| `state` | Binary | Serialized MontyFutureSnapshot |
| `status` | String(20) | 'running', 'waiting', 'completed', 'failed' |
| `current_resume_group_id` | String(36) | Which group we're waiting for |
| `inputs` | Text | JSON - initial inputs |
| `output` | Text | JSON - final result |

### Calls Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Auto-increment |
| `execution_id` | String(36) | FK to executions |
| `resume_group_id` | String(36) | Group this call belongs to |
| `call_id` | Integer | Monty's internal call_id |
| `function_name` | String(100) | Which function to execute |
| `args` | Text | JSON - function arguments |
| `status` | String(20) | 'pending', 'running', 'completed', 'failed' |
| `result` | Text | JSON - result when done |
| `error` | Text | Error message if failed |

**Key index:** `(resume_group_id, status)` for fast "is group complete?" queries

## Concurrency & Safety

### Worker Concurrency

RQ handles job distribution automatically:
- Workers pick jobs from Redis queue
- No locking needed - RQ ensures each job goes to one worker
- Multiple workers can process different calls in parallel

### Resume Concurrency

**Problem:** Multiple workers might complete at the same time and all try to resume.

**Solution:** Use database transaction + check:

```python
def check_and_resume_if_ready(execution_id, resume_group_id):
    with session.begin():  # Transaction
        # Count completed vs total
        total = session.query(Call).filter_by(resume_group_id=resume_group_id).count()
        completed = session.query(Call).filter_by(
            resume_group_id=resume_group_id,
            status='completed'
        ).count()

        if total == completed:
            # Check if already resumed
            execution = session.query(Execution).filter_by(id=execution_id).first()
            if execution.status == 'waiting':
                # We're first! Mark as running to prevent others
                execution.status = 'running'
                session.commit()
                # Now resume (outside transaction)
                resume_execution(execution_id, resume_group_id)
```

## Error Handling

### Task Failure

**Option 1:** Fail entire execution if any task fails
```python
if any_failed:
    execution.status = 'failed'
```

**Option 2:** Retry failed tasks (TODO)
```python
if call.status == 'failed' and call.retry_count < MAX_RETRIES:
    call.retry_count += 1
    call.status = 'pending'
    enqueue_task(...)
```

### Resume Failure

If resume fails (code error, etc.):
- Mark execution as 'failed'
- Store error in execution.output
- Don't retry automatically (could loop forever)

## Performance Considerations

### State Size

- ~800 bytes per snapshot
- Scales with workflow complexity (stack depth, variables)
- Much smaller than event-sourced approaches (Temporal stores full history)

### Database Queries

**Hot path queries:**
1. Check if resume group complete (per task completion)
   ```sql
   SELECT COUNT(*) total, COUNT(*) FILTER (WHERE status='completed') done
   FROM calls WHERE resume_group_id = ?
   ```

2. Load state for resume
   ```sql
   SELECT state FROM executions WHERE id = ?
   ```

3. Load results for resume
   ```sql
   SELECT call_id, result FROM calls
   WHERE resume_group_id = ? AND status = 'completed'
   ```

**Optimization:** Index on `(resume_group_id, status)`

### Worker Scaling

- RQ workers are stateless - scale horizontally
- Add more workers for higher throughput
- Each worker can handle different function types

## Deployment Options

### Development (SQLite)

```python
engine = create_engine('sqlite:///durable.db')
# Single process: orchestrator + worker in same process
```

### Production (Postgres + Multiple Workers)

```python
engine = create_engine('postgresql://user:pass@localhost/durable')

# Process 1: API + Orchestrator
# Process 2-N: RQ Workers
# rq worker durable-tasks
```

### Single Server (Lean Setup)

- Postgres for state
- Redis for RQ
- 1 orchestrator process
- N worker processes
- All on same VPS

### Multi-Server (Scale Out)

- Managed Postgres (RDS, etc.)
- Managed Redis (ElastiCache, etc.)
- Multiple worker servers
- Orchestrator on separate server(s)