# Project Plan

## Overview

Build a POC (Proof of Concept) implementation of durable-monty - a durable functions framework using monty-python.

**Goal:** Demonstrate that real Python async/await code can be made durable with state persistence, parallel execution, and automatic resume.

**Target:** Working system that can run the video encoding example from README.md.

## Phase 1: Core Foundation (Days 1-2)

### Task 1.1: Project Setup
- [x] Create repository structure
- [ ] Create `pyproject.toml` with dependencies
- [ ] Create `__init__.py` files
- [ ] Setup .gitignore
- [ ] Create requirements for dev/test

**Dependencies:**
- pydantic-monty
- sqlalchemy
- rq
- redis
- pytest (dev)

### Task 1.2: Database Models
**File:** `durable_monty/models.py`

- [ ] Define `Execution` model
  - All columns as specified in ARCHITECTURE.md
  - JSON helper methods
- [ ] Define `Call` model
  - All columns + indexes
  - Relationship to Execution
- [ ] Add `to_json()` and `from_json()` helpers
- [ ] Write unit tests for models

**Acceptance criteria:**
- Can create tables in SQLite
- Can insert and query Execution/Call records
- JSON serialization works
- Relationships work (cascade delete)

### Task 1.3: Database Setup
**File:** `durable_monty/db.py`

- [ ] `init_db(connection_string)` function
  - Create engine
  - Create all tables
  - Return engine
- [ ] Test with SQLite, Postgres (optional for POC)
- [ ] Add session management helpers

**Acceptance criteria:**
- `init_db('sqlite:///test.db')` creates database
- Tables exist with correct schema
- Can get sessions and query

## Phase 2: Function Registry (Day 2)

### Task 2.1: Function Registry
**File:** `durable_monty/functions.py`

- [ ] Create `FUNCTION_REGISTRY` dict
- [ ] Create `@register_function(name)` decorator
- [ ] Add example functions (add, multiply)
- [ ] Write tests

**Acceptance criteria:**
- Can register functions
- Can call registered functions by name
- Registry persists across imports

## Phase 3: Orchestrator (Days 3-4)

### Task 3.1: Start Execution
**File:** `durable_monty/orchestrator.py`

- [ ] Implement `start_execution()`
  - Create Monty instance
  - Start and collect MontySnapshots
  - Mark as futures
  - Handle MontyFutureSnapshot
  - Generate resume_group_id
  - Save Execution and Calls to DB
  - Return execution_id
- [ ] Handle edge case: immediate completion (no external calls)
- [ ] Write tests (with mocked DB and RQ)

**Acceptance criteria:**
- Can start simple workflow
- State saved to database correctly
- All calls recorded with resume_group_id
- Returns execution_id

### Task 3.2: Resume Execution
**File:** `durable_monty/orchestrator.py`

- [ ] Implement `resume_execution()`
  - Load state from DB
  - Load results for resume_group_id
  - Deserialize MontyFutureSnapshot
  - Resume with results
  - Handle MontyComplete (save output)
  - Handle MontyFutureSnapshot (nested gather)
- [ ] Write tests

**Acceptance criteria:**
- Can resume execution with results
- Handles completion correctly
- Handles nested gather (creates new group)
- Updates DB correctly

## Phase 4: Worker (Days 4-5)

### Task 4.1: RQ Integration
**File:** `durable_monty/worker.py`

- [ ] Setup Redis connection
- [ ] Create RQ queue
- [ ] Implement `enqueue_calls()`
  - Enqueue each call to RQ
  - Pass all necessary data
- [ ] Write tests (mock RQ)

**Acceptance criteria:**
- Can enqueue calls to RQ
- Jobs appear in Redis queue
- Job data is correct

### Task 4.2: Execute and Save Wrapper
**File:** `durable_monty/worker.py`

- [ ] Implement `execute_and_save()`
  - Call function from registry
  - Save result to DB
  - Handle exceptions
  - Call check_and_resume_if_ready
- [ ] Write tests

**Acceptance criteria:**
- Executes function correctly
- Saves result to database
- Handles errors gracefully
- Triggers resume check

### Task 4.3: Resume Check and Trigger
**File:** `durable_monty/worker.py`

- [ ] Implement `check_and_resume_if_ready()`
  - Count total/completed/failed calls
  - Check if all done
  - Prevent double-resume
  - Call resume_execution if ready
- [ ] Write tests

**Acceptance criteria:**
- Correctly detects when group is complete
- Prevents race conditions
- Triggers resume exactly once
- Handles failures in group

## Phase 5: Examples and Testing (Days 5-6)

### Task 5.1: Simple Example
**File:** `examples/simple_parallel.py`

- [ ] Create simple add/multiply example
- [ ] Register functions
- [ ] Define workflow code
- [ ] Start execution
- [ ] Verify it works end-to-end

**Acceptance criteria:**
- Example runs successfully
- Tasks execute in parallel
- Execution completes with correct result

### Task 5.2: Video Encoding Example
**File:** `examples/video_encoding.py`

- [ ] Implement mock `encode_video` function
- [ ] Implement mock `create_playlist` function
- [ ] Create workflow from README example
- [ ] Run and verify

**Acceptance criteria:**
- Encodes multiple videos in parallel
- Creates playlist after encoding
- Returns correct output

### Task 5.3: Integration Tests
**File:** `tests/test_integration.py`

- [ ] End-to-end test with real RQ workers
- [ ] Test nested gather
- [ ] Test error handling
- [ ] Test serialization/deserialization

**Acceptance criteria:**
- All tests pass
- Coverage > 80%
- Edge cases handled

## Phase 6: Polish and Documentation (Day 6-7)

### Task 6.1: CLI/Scripts
**File:** `scripts/run_worker.py`

- [ ] Create worker startup script
- [ ] Add command-line arguments
- [ ] Add logging

**Acceptance criteria:**
- Can start worker easily
- Logs are helpful
- Can configure queue name

### Task 6.2: Error Handling
**Files:** Various

- [ ] Add proper error messages
- [ ] Log errors appropriately
- [ ] Handle all edge cases
- [ ] Add validation

### Task 6.3: Documentation
**Files:** README, examples

- [ ] Update README with installation instructions
- [ ] Add quickstart guide
- [ ] Document all public APIs
- [ ] Add troubleshooting section

## Phase 7: Optional Enhancements

### Task 7.1: Retry Logic
- [ ] Add retry_count to Call model
- [ ] Implement exponential backoff
- [ ] Add max_retries configuration

### Task 7.2: API Layer
**File:** `durable_monty/api.py`

- [ ] FastAPI app
- [ ] POST /executions (start)
- [ ] GET /executions/{id} (status)
- [ ] GET /executions/{id}/calls (list calls)

### Task 7.3: Dashboard
- [ ] Simple web UI
- [ ] List executions
- [ ] View execution details
- [ ] View call tree

## Development Guidelines

### Code Quality
- Use type hints
- Add docstrings
- Follow PEP 8
- Run ruff/black

### Testing
- Write tests for each function
- Aim for >80% coverage
- Test edge cases
- Use pytest fixtures

### Git Workflow
- Commit often
- Write clear commit messages
- Use feature branches for major features
- Tag releases

### Documentation
- Keep README up to date
- Document all public APIs
- Add examples for common use cases
- Write clear error messages

## Success Criteria

### MVP Success (End of Phase 5)
- ✅ Can start a workflow with parallel tasks
- ✅ Tasks execute in parallel on RQ workers
- ✅ State persists to database
- ✅ Execution resumes automatically when tasks complete
- ✅ Video encoding example works
- ✅ Basic tests pass

### Production Ready (Future)
- Error handling and retries
- Monitoring and logging
- API layer
- Dashboard
- Documentation
- Performance testing
- Security review

## Timeline

**Week 1:** Core implementation (Phases 1-5)
- Day 1-2: Models, DB, Registry
- Day 3-4: Orchestrator, Worker
- Day 5-6: Examples, Testing
- Day 7: Polish, Documentation

**Week 2+:** Enhancements (Phase 7)
- Retry logic
- API layer
- Dashboard
- Production hardening

## Risks and Mitigations

### Risk: Nested gather complexity
**Mitigation:** Test early and often, keep logic simple, add extensive logging

### Risk: Race conditions in resume
**Mitigation:** Use database transactions, add tests for concurrency

### Risk: Large state snapshots
**Mitigation:** Monitor snapshot sizes, optimize if needed, add limits

### Risk: Function registry limitations
**Mitigation:** Document limitations, provide clear examples, consider dynamic loading

## Getting Started

To start implementing:

1. Read all markdown files (README, ARCHITECTURE, IMPLEMENTATION)
2. Start with Task 1.1 (Project Setup)
3. Work through tasks sequentially
4. Test each component before moving on
5. Keep it simple - get MVP working first
6. Add enhancements later

## Questions to Resolve

- [ ] How to handle very long-running executions? (weeks/months)
- [ ] How to handle execution cancellation?
- [ ] How to handle function versioning? (code changes after execution starts)
- [ ] How to handle large arguments/results? (GB of data)
- [ ] How to monitor/debug stuck executions?

These can be addressed after MVP is working.