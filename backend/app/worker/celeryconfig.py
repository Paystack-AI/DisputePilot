from celery.schedules import crontab
from kombu import Exchange, Queue

task_acks_late = True
worker_concurrency = 100
task_reject_on_worker_lost = True
worker_prefetch_multiplier = 1

dlx: Exchange = Exchange("disputepilot.dlx", type="direct")
direct: Exchange = Exchange("disputepilot.direct", type="direct")

# messages rejected or expired on disputepilot.celery are re-routed to the dlq
queue_arguments: dict = {
    "x-max-priority": 10,
    "x-dead-letter-exchange": "disputepilot.dlx",
    "x-dead-letter-routing-key": "dlq",
}

task_queues = (
    Queue("disputepilot.dlq", dlx, routing_key="dlq"),
    Queue("disputepilot.celery", direct, routing_key="celery", queue_arguments=queue_arguments),
)

task_default_queue = "disputepilot.celery"
task_default_exchange = "disputepilot.direct"
task_default_routing_key = "celery"

# run by celery beat; times are utc
beat_schedule: dict = {
    "daily-transaction-sync": {
        "task": "app.worker.tasks.transaction_sync.schedule_transaction_syncs",
        "schedule": crontab(hour=1, minute=0),
        "options": {"priority": 4},
    },
}
