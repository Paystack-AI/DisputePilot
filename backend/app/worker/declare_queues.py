"""One-shot queue declaration.

Celery only asks the broker to create a queue when some worker actually
consumes from it (`-Q ...`). disputepilot.dlq is deliberately never consumed
by any worker - a dead-lettered task landing there shouldn't be picked back up
and re-executed as if it were a fresh delivery - so no worker ever declares
it. Run this once (before the workers start) to declare every queue in
task_queues, including disputepilot.dlq, without subscribing to any of them.
"""

from app.worker.celery_app import celery_app


def declare_queues():
    with celery_app.connection_or_acquire() as conn:
        channel = conn.default_channel
        for queue in celery_app.amqp.queues.values():
            queue.bind(channel).declare()


if __name__ == "__main__":
    declare_queues()
