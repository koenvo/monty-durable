## Execution Engines

Durable-monty uses pluggable executors to run function calls. The default is local execution, but you can use RQ, Modal, AWS Lambda, or create your own.

## Built-in Executors

### LocalExecutor (Default)
Executes functions in the same process. Good for development and testing.

```python
from durable_monty import Worker, LocalExecutor

executor = LocalExecutor()
worker = Worker(service, executor=executor)
worker.run()
```

### RQExecutor
Executes functions using Redis Queue for distributed execution.

```python
from durable_monty import Worker, RQExecutor

executor = RQExecutor(queue_name="my-queue")
worker = Worker(service, executor=executor)
worker.run()
```

**Requirements:**
- Redis server running
- RQ workers running: `rq worker my-queue`
- Functions registered in worker processes

## Creating Custom Executors

### Example: ModalExecutor

```python
from durable_monty.executor import Executor
from durable_monty.models import Call, from_json
import modal

class ModalExecutor(Executor):
    """Execute functions on Modal.com"""

    def __init__(self):
        self.app = modal.App("durable-monty")
        self.stats = {"submitted": 0}

    def submit_call(self, call: Call) -> None:
        """Submit call to Modal."""
        args = from_json(call.args)

        # Create Modal function
        @self.app.function()
        def run_function():
            from durable_monty import init_db, OrchestratorService
            from durable_monty.functions import execute_function

            result = execute_function(call.function_name, args)

            # Save result
            service = OrchestratorService(init_db())
            service.complete_call(call.execution_id, call.call_id, result)

            return result

        # Submit to Modal
        run_function.remote()
        self.stats["submitted"] += 1

    def get_stats(self) -> dict:
        return self.stats
```

### Example: LambdaExecutor

```python
import boto3
from durable_monty.executor import Executor
from durable_monty.models import Call, from_json, to_json

class LambdaExecutor(Executor):
    """Execute functions on AWS Lambda"""

    def __init__(self, function_name: str):
        self.lambda_client = boto3.client('lambda')
        self.function_name = function_name
        self.stats = {"invoked": 0}

    def submit_call(self, call: Call) -> None:
        """Submit call to Lambda."""
        payload = {
            "execution_id": call.execution_id,
            "call_id": call.call_id,
            "function_name": call.function_name,
            "args": from_json(call.args),
        }

        # Invoke Lambda asynchronously
        self.lambda_client.invoke(
            FunctionName=self.function_name,
            InvocationType='Event',  # Async
            Payload=to_json(payload),
        )

        self.stats["invoked"] += 1

    def get_stats(self) -> dict:
        return self.stats
```

**Lambda handler** (deployed to AWS):
```python
def handler(event, context):
    from durable_monty.functions import execute_function

    # Just execute and return - no DB access needed!
    result = execute_function(
        event["function_name"],
        event["args"]
    )

    return {"result": result}
```

**Note:** The main worker polls Lambda/RQ/Modal jobs using stored `job_id` and updates the database when complete. Workers don't need database access!

## Executor Interface

All executors must implement:

```python
class Executor(ABC):
    @abstractmethod
    def submit_call(self, call: Call) -> None:
        """Submit a call for execution."""
        pass

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """Get executor statistics."""
        pass
```

### Key Requirements

1. **Async execution**: Executors should submit work and return immediately
2. **Result persistence**: Executor (or worker function) must call `service.complete_call()`
3. **Error handling**: Failed calls should be marked with status="failed"
4. **Function registry**: Worker processes must have access to registered functions

## Usage

```python
from durable_monty import init_db, OrchestratorService, Worker
from my_executors import ModalExecutor

# Setup
engine = init_db()
service = OrchestratorService(engine)
executor = ModalExecutor()

# Run worker with custom executor
worker = Worker(service, executor=executor)
worker.run()
```

## Architecture

```
User → start_execution() → "scheduled"
           ↓
Worker → _process_execution() → creates calls → "waiting"
           ↓
Worker → executor.submit_call() → RQ/Modal/Lambda
           ↓
Remote worker → execute_function() → service.complete_call()
           ↓
Worker → poll() → resumes → "completed"
```
