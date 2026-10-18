from __future__ import annotations

import argparse
import json
import time

from backend.services.action_execution_worker import ActionExecutionWorker
from backend.services.action_queue_backend import RedisActionQueueBackend


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Stage 06 Meta action execution worker.")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--consumer-name", default="action-worker-1")
    parser.add_argument("--group-name", default="action-workers")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=2.0)
    parser.add_argument("--max-iterations", type=int, default=0)
    parser.add_argument("--stale-min-idle-ms", type=int, default=60000)
    args = parser.parse_args()

    backend = RedisActionQueueBackend(
        redis_url=args.redis_url,
        group_name=args.group_name,
        consumer_name=args.consumer_name,
    )
    worker = ActionExecutionWorker(queue_backend=backend)

    iterations = 0
    while True:
        result = worker.process_next(stale_min_idle_ms=args.stale_min_idle_ms)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        iterations += 1
        if args.once or (args.max_iterations and iterations >= args.max_iterations):
            return 0
        if not result.get("processed"):
            time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
