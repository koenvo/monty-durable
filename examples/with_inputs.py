import logging
import time

from durable_monty import init_db, OrchestratorService, Worker, register_function, LocalExecutor

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)

@register_function("process")
def process(item, index):
    # time.sleep(1)
    return f"processed_{item}_{index}"


def sync_method(a, b):
    return f"hi_{a}_{b}"


code = """
from asyncio import gather
results = await gather(
    process('a', i),
    process('b', i),
    process('c', i)
)
results += [await process('d', i)]
results += [sync_method('e', i)]
print(results)
results
"""

service = OrchestratorService(init_db())


import threading

worker = Worker(service, LocalExecutor(), poll_interval=0.1)


thread = threading.Thread(target=worker.run)
thread.start()

exec_ids = []
for i in range(10):
    exec_id = service.start_execution(code, ["process", "sync_method"], {"i": i})
    exec_ids.append(exec_id)

time.sleep(100)

worker.stop()

for exec_id in exec_ids:
    print(f"Result: {service.get_result(exec_id)}")

