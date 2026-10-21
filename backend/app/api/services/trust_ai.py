"""What the ai sends back for TrustLayer (it only explains; the policy decides the state).

ai:result:trust-explained          the profile's explanation and recommended actions;
                                   applied only for the explain job the profile waits on
ai:result:state-change-summarized  one line for a state change; the job id is the snapshot's
"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models.trust_profiles import TrustProfile
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.repo.trust import TrustRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.services.ai_streams import AI_RESULT_HANDLERS, StreamMessage
from app.api.services.events import publish_event
from app.database.session import async_session, redis_client

TRUST_EXPLAINED: str = "ai:result:trust-explained"
STATE_CHANGE_SUMMARIZED: str = "ai:result:state-change-summarized"
# the fields a recommended action keeps; anything else the model adds is dropped
ACTION_FIELDS: tuple[str, ...] = ("action", "impact_description", "affected_signal")
MAX_ACTIONS: int = 5

# swapped in tests; handlers run outside a request
session_factory: Callable[[], AsyncSession] = async_session
redis_factory: Callable[[], Redis] = lambda: redis_client  # noqa: E731


def _actions(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    actions: list[dict] = []
    for item in value[:MAX_ACTIONS]:
        if isinstance(item, dict) and isinstance(item.get("action"), str) and item["action"]:
            actions.append({field: str(item.get(field) or "") for field in ACTION_FIELDS})
    return actions


async def on_trust_explained(message: StreamMessage):
    merchant_id = message.payload.get("merchantId")
    explanation = message.payload.get("explanation")
    if not merchant_id or not isinstance(explanation, str) or not explanation.strip():
        return

    async with session_factory() as session:
        uow = UnitOfWorkRepository(session)
        profile: TrustProfile | None = await uow.repo(TrustRepository).profile_for_update(
            UUID(merchant_id)
        )
        if not profile or profile.explain_job_id != message.job_id:
            sentry_logger.info(
                "Ignored trust explanation for job {job_id}: no longer waited on",
                job_id=message.job_id,
            )
            return
        profile.explanation = explanation.strip()
        profile.recommendations = _actions(message.payload.get("recommendations"))
        profile.explained_at = datetime.now(UTC)
        profile.explain_job_id = None
        await uow.commit()
        actions: int = len(profile.recommendations)

    try:
        await publish_event(
            redis_factory(),
            merchant_id,
            "trust.explained",
            {"explanation": explanation.strip(), "actions": actions},
        )
    except Exception as exc:
        sentry_sdk.capture_exception(exc)


async def on_state_change_summarized(message: StreamMessage):
    summary = message.payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return
    try:
        snapshot_id = UUID(message.job_id)
    except ValueError:
        return

    async with session_factory() as session:
        uow = UnitOfWorkRepository(session)
        snapshot: TrustSnapshot | None = await uow.repo(TrustRepository).snapshot_for_update(
            snapshot_id
        )
        if not snapshot or str(snapshot.merchant_id) != message.payload.get("merchantId"):
            return
        snapshot.summary = summary.strip()[:500]
        await uow.commit()


AI_RESULT_HANDLERS.update(
    {
        TRUST_EXPLAINED: on_trust_explained,
        STATE_CHANGE_SUMMARIZED: on_state_change_summarized,
    }
)
