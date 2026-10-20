from celery import Celery

from app.core.config import get_settings

SETTINGS = get_settings()

tasks: list[str] = [
    "app.worker.tasks.email",
    "app.worker.tasks.files",
    "app.worker.tasks.transaction_sync",
    "app.worker.tasks.webhooks",
    "app.worker.tasks.disputes",
    "app.worker.tasks.dispute_submission",
]

celery_app = Celery(
    main="celery_app",
    broker=SETTINGS.BROKER_URL,
    backend=SETTINGS.REDIS_URL,
    include=tasks,
)

celery_app.config_from_object("app.worker.celeryconfig")
