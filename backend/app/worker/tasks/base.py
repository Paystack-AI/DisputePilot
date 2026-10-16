import random

from celery import Task
from celery.exceptions import Reject


class BaseTaskWithRetry(Task):
    """Retries transient failures with jittered exponential backoff. Once retries
    run out, or the failure is permanent, the message is rejected without requeue
    so the broker dead-letters it to disputepilot.dlq."""

    max_retries = 5

    # double the delay on every retry, capped at retry_backoff_max seconds
    retry_backoff = 2
    retry_backoff_max = 600

    # randomise each delay so tasks that failed together don't retry together
    retry_jitter = True

    def _backoff_countdown(self) -> int:
        countdown: int = min(self.retry_backoff * (2**self.request.retries), self.retry_backoff_max)

        if self.retry_jitter:
            countdown = random.randrange(int(countdown * 0.5), int(countdown * 1.5) + 1)
        return countdown

    def retry_or_reject(self, exc: Exception):
        if self.request.retries >= self.max_retries:
            raise Reject(exc, requeue=False) from exc
        raise self.retry(exc=exc, countdown=self._backoff_countdown())
