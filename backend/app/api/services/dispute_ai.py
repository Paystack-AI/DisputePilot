"""The evidence chain over the ai streams (spec 4.4): classify -> generate -> score.

The backend sends one step at a time and moves on when its result arrives
(AI_RESULT_HANDLERS). Each step carries its own job id, stored on the dispute; a result for
any other job (an older run, a duplicate delivery) is ignored. A step that errors, or has no
result within AI_STEP_TIMEOUT_SECONDS, falls back instead of stalling:
  classify -> the keyword classifier, then generate as usual
  generate -> the template narrative for the category; the draft is ready, unscored
  score    -> the draft is ready, unscored
When the chain ends the full evidence document goes to the dashboard as evidence.ready.
"""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models.disputes import Dispute
from app.api.models.enums import (
    DisputeCategory,
    DisputeStatus,
    EvidenceChange,
    EvidenceState,
    EvidenceStep,
    GenerationSource,
    SubmissionFlow,
)
from app.api.models.evidence_revisions import EvidenceRevision
from app.api.models.merchants import Merchant
from app.api.repo.disputes import DisputeRepository
from app.api.repo.ai_memory import AiMemoryRepository
from app.api.repo.merchants import MerchantRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.disputes import EvidenceDocument
from app.api.services.ai_streams import AI_RESULT_HANDLERS, AiStreamPublisher, StreamMessage
from app.api.services.events import publish_event
from app.api.services.evidence_document import EvidenceContext, EvidenceDocumentBuilder
from app.api.services.evidence_templates import (
    classify_by_keywords,
    submission_flow,
    template_conclusion,
    template_narrative,
)
from app.core.config import get_settings
from app.database.session import async_session, redis_client

SETTINGS = get_settings()

# backend -> ai
CLASSIFY: str = "ai:dispute:classify"
GENERATE: str = "ai:dispute:generate-evidence"
SCORE: str = "ai:dispute:score-quality"
REQUESTS: dict[EvidenceStep, str] = {
    EvidenceStep.CLASSIFY: CLASSIFY,
    EvidenceStep.GENERATE: GENERATE,
    EvidenceStep.SCORE: SCORE,
}
# ai -> backend
CLASSIFIED: str = "ai:result:classified"
GENERATED: str = "ai:result:evidence-generated"
SCORED: str = "ai:result:quality-scored"
AI_ERROR: str = "ai:error"
# timed out steps handled per sweep
SWEEP_BATCH: int = 20

# swapped in tests; handlers and the sweep run outside a request
session_factory: Callable[[], AsyncSession] = async_session
redis_factory: Callable[[], Redis] = lambda: redis_client  # noqa: E731


def _available_items(document: EvidenceDocument) -> list[str]:
    items: list[str] = ["transaction_receipt"]
    if document.order_details:
        items.append("order_details")
    if document.fulfillment_evidence:
        items.append("fulfillment_record")
        if any(f.tracking_number for f in document.fulfillment_evidence):
            items.append("tracking_number")
        if any(f.recipient_name for f in document.fulfillment_evidence):
            items.append("signed_confirmation")
        if any(f.photos for f in document.fulfillment_evidence):
            items.append("delivery_photo")
    if document.supporting_documents:
        items.append("supporting_documents")
    if document.customer_history:
        items.append("customer_history")
    return items


class EvidenceChain:
    def __init__(self, uow: UnitOfWorkRepository, redis: Redis):
        self._uow = uow
        self._redis = redis
        self._disputes = uow.repo(DisputeRepository)
        self._memory = uow.repo(AiMemoryRepository)
        self._builder = EvidenceDocumentBuilder(uow)

    # ------------------------------ steps ------------------------------ #

    async def _context(self, dispute: Dispute) -> EvidenceContext:
        return await self._builder.load(await self._disputes.links_of(dispute))

    async def _payload(self, merchant: Merchant, dispute: Dispute, step: EvidenceStep) -> dict:
        if step == EvidenceStep.CLASSIFY:
            channel = await self._disputes.transaction_channel(dispute.transaction_id)
            return {
                "disputeId": str(dispute.id),
                "messagesBody": dispute.reason_raw,
                "paystackCategory": dispute.paystack_category,
                "transactionChannel": channel.value if channel else None,
                "hasEvidenceObject": dispute.paystack_evidence_id is not None,
            }

        context: EvidenceContext = await self._context(dispute)
        document: EvidenceDocument = self._builder.build(merchant, context)
        if step == EvidenceStep.GENERATE:
            payload = self._builder.ai_context(document, dispute, context.transaction)
            try:
                revisions = await self._disputes.all_revisions(dispute.id)
                for revision in revisions:
                    await self._memory.remember(
                        tenant_id=merchant.id,
                        merchant_id=merchant.id,
                        dispute_id=dispute.id,
                        memory_type="evidence_revision",
                        source_type="evidence_revision",
                        source_id=str(revision.id),
                        content={
                            "version": revision.version,
                            "change": revision.change.value,
                            "reason": revision.reason,
                            "narrative": revision.narrative,
                            "conclusion": revision.conclusion,
                        },
                        occurred_at=revision.created_at,
                    )
                memories = await self._memory.retrieve(
                    tenant_id=merchant.id,
                    merchant_id=merchant.id,
                    dispute_id=dispute.id,
                    query=f"{dispute.reason_raw or ''} {dispute.category or ''}",
                    limit=SETTINGS.AI_MEMORY_CONTEXT_LIMIT,
                )
                payload["memory"] = [
                    {
                        "source_type": item.source_type,
                        "source_id": item.source_id,
                        "occurred_at": item.occurred_at.isoformat(),
                        "content": item.content,
                    }
                    for item in memories
                ]
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
                sentry_logger.warning(
                    "AI memory retrieval failed for dispute {dispute_id}; continuing without memory",
                    dispute_id=str(dispute.id),
                )
                payload["memory"] = []
            return payload
        return {
            "disputeId": str(dispute.id),
            "narrative": dispute.evidence_narrative,
            "category": dispute.category.value if dispute.category else None,
            "availableEvidenceItems": _available_items(document),
            "evidenceItemsReferenced": dispute.evidence_items_referenced or [],
        }

    async def send(self, merchant: Merchant, dispute: Dispute, step: EvidenceStep):
        """Starts a step: records it on the (locked) dispute, commits, then hands it to the
        ai. If the hand-off fails the step times out and falls back"""
        job_id: str = str(uuid.uuid4())
        payload: dict = await self._payload(merchant, dispute, step)

        dispute.evidence_state = EvidenceState.GENERATING
        dispute.evidence_step = step
        dispute.ai_job_id = job_id
        dispute.evidence_step_started_at = datetime.now(UTC)
        await self._uow.commit()

        try:
            await AiStreamPublisher(self._redis).publish(REQUESTS[step], payload, job_id=job_id)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Evidence step {step} for dispute {dispute_id} could not be sent",
                step=step.value,
                dispute_id=str(dispute.id),
            )
        await self._event(
            merchant.id, "evidence.progress", {"dispute_id": str(dispute.id), "step": step.value}
        )

    async def finish(self, merchant: Merchant, dispute: Dispute):
        """The draft is ready: a new version, recorded as a revision, sent to the dashboard"""
        now: datetime = datetime.now(UTC)
        dispute.evidence_state = EvidenceState.READY
        dispute.evidence_step = None
        dispute.ai_job_id = None
        dispute.evidence_step_started_at = None
        dispute.evidence_version += 1
        dispute.generated_at = now
        if dispute.status == DisputeStatus.PENDING:
            dispute.status = DisputeStatus.EVIDENCE_GENERATED

        context: EvidenceContext = await self._context(dispute)
        revision = self._disputes.add_revision(
            EvidenceRevision(
                dispute_id=dispute.id,
                merchant_id=merchant.id,
                version=dispute.evidence_version,
                change=EvidenceChange.GENERATED,
                reason=f"Generated ({dispute.generation_source.value})",
                narrative=dispute.evidence_narrative,
                conclusion=dispute.evidence_conclusion,
                documents=[{"file_id": str(d.id), "caption": d.caption} for d in context.documents],
                created_at=now,
            )
        )
        await self._uow.flush()
        await self._memory.remember(
            tenant_id=merchant.id,
            merchant_id=merchant.id,
            dispute_id=dispute.id,
            memory_type="evidence_revision",
            source_type="evidence_revision",
            source_id=str(revision.id),
            content={
                "version": revision.version,
                "change": revision.change.value,
                "reason": revision.reason,
                "narrative": revision.narrative,
                "conclusion": revision.conclusion,
            },
            occurred_at=revision.created_at,
        )
        await self._uow.commit()

        document: EvidenceDocument = self._builder.build(merchant, context)
        await self._event(
            merchant.id,
            "evidence.ready",
            {"dispute_id": str(dispute.id), "evidence": document.model_dump(mode="json")},
        )
        sentry_logger.info(
            "Evidence for dispute {dispute_id} ready ({source})",
            dispute_id=str(dispute.id),
            source=dispute.generation_source.value,
        )

    async def _event(self, merchant_id: UUID, event_type: str, data: dict):
        try:
            await publish_event(self._redis, merchant_id, event_type, data)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "{event_type} could not be published for merchant {merchant_id}",
                event_type=event_type,
                merchant_id=str(merchant_id),
            )

    # ------------------------------ results ------------------------------ #

    async def classified(self, merchant: Merchant, dispute: Dispute, payload: dict):
        try:
            category = DisputeCategory(payload.get("category"))
        except ValueError:
            category = None
        if category is None:
            await self.step_failed(merchant, dispute, "unknown category")
            return

        try:
            flow = SubmissionFlow(payload.get("submissionFlow"))
        except ValueError:
            flow = submission_flow(category)
        # fraud always needs the identity step, whatever the flow says
        if category == DisputeCategory.FRAUD:
            flow = SubmissionFlow.FRAUD_FLOW

        dispute.category = category
        dispute.submission_flow = flow
        confidence = payload.get("confidence")
        dispute.category_confidence = (
            float(confidence) if isinstance(confidence, int | float) else None
        )
        strategy = payload.get("evidenceStrategy")
        dispute.evidence_strategy = strategy if isinstance(strategy, list) else None
        instructions = payload.get("specialInstructions")
        dispute.special_instructions = instructions if isinstance(instructions, str) else None

        await self.send(merchant, dispute, EvidenceStep.GENERATE)

    async def generated(self, merchant: Merchant, dispute: Dispute, payload: dict):
        narrative = payload.get("narrative")
        if not isinstance(narrative, str) or not narrative.strip():
            await self.step_failed(merchant, dispute, "empty narrative")
            return

        conclusion = payload.get("conclusion")
        dispute.evidence_narrative = narrative.strip()
        dispute.evidence_conclusion = (
            conclusion.strip()
            if isinstance(conclusion, str) and conclusion.strip()
            else template_conclusion(dispute.category)
        )
        missing = payload.get("missingEvidence")
        dispute.missing_evidence = missing if isinstance(missing, list) else None
        referenced = payload.get("evidenceItemsReferenced")
        dispute.evidence_items_referenced = referenced if isinstance(referenced, list) else None
        dispute.generation_source = GenerationSource.AI

        await self.send(merchant, dispute, EvidenceStep.SCORE)

    async def scored(self, merchant: Merchant, dispute: Dispute, payload: dict):
        score = payload.get("overallScore")
        if isinstance(score, int | float):
            dispute.evidence_quality_score = float(max(0, min(100, score)))
            suggestions = payload.get("suggestions")
            dispute.evidence_suggestions = suggestions if isinstance(suggestions, list) else []
            dimensions = payload.get("dimensionScores")
            dispute.evidence_quality = {
                # whole numbers, as the api shows them (models may send 72.5)
                "dimension_scores": (
                    {
                        key: round(value)
                        for key, value in dimensions.items()
                        if isinstance(value, int | float)
                    }
                    if isinstance(dimensions, dict)
                    else None
                ),
                "ready_to_submit": payload.get("readyToSubmit"),
            }
        await self.finish(merchant, dispute)

    async def step_failed(self, merchant: Merchant, dispute: Dispute, reason: str):
        """The current step errored or timed out: fall back for that step"""
        step: EvidenceStep | None = dispute.evidence_step
        sentry_logger.warning(
            "Evidence step {step} for dispute {dispute_id} failed: {reason}",
            step=str(step),
            dispute_id=str(dispute.id),
            reason=reason,
        )

        if step == EvidenceStep.CLASSIFY:
            category, confidence = classify_by_keywords(dispute.reason_raw)
            dispute.category = category
            dispute.category_confidence = confidence
            dispute.submission_flow = submission_flow(category)
            await self.send(merchant, dispute, EvidenceStep.GENERATE)
            return

        if step == EvidenceStep.GENERATE:
            context: EvidenceContext = await self._context(dispute)
            document: EvidenceDocument = self._builder.build(merchant, context)
            dispute.evidence_narrative = template_narrative(document, dispute.category)
            dispute.evidence_conclusion = template_conclusion(dispute.category)
            dispute.generation_source = GenerationSource.TEMPLATE
            # a template is not scored: the merchant is told the ai did not write it
            dispute.evidence_quality_score = None
            dispute.evidence_quality = None
            dispute.evidence_suggestions = None

        # score failing keeps the ai's draft, unscored
        await self.finish(merchant, dispute)


# ------------------------------ stream handlers ------------------------------ #


async def _handle(message: StreamMessage, step: EvidenceStep, action: str):
    """Runs a result against its dispute if it answers the step the dispute is waiting on"""
    dispute_id = message.payload.get("disputeId")
    if not dispute_id:
        return

    async with session_factory() as session:
        uow = UnitOfWorkRepository(session)
        dispute: Dispute | None = await uow.repo(DisputeRepository).get_by_id_for_update(
            UUID(dispute_id)
        )
        if (
            not dispute
            or dispute.evidence_state != EvidenceState.GENERATING
            or dispute.ai_job_id != message.job_id
            or (step is not None and dispute.evidence_step != step)
        ):
            sentry_logger.info(
                "Ignored {event} for job {job_id}: no longer waited on",
                event=message.event,
                job_id=message.job_id,
            )
            return

        merchant: Merchant = await uow.repo(MerchantRepository).get_profile(dispute.merchant_id)
        chain = EvidenceChain(uow, redis_factory())
        if action == "error":
            await chain.step_failed(merchant, dispute, str(message.payload.get("error")))
        else:
            await getattr(chain, action)(merchant, dispute, message.payload)


async def on_classified(message: StreamMessage):
    await _handle(message, EvidenceStep.CLASSIFY, "classified")


async def on_generated(message: StreamMessage):
    await _handle(message, EvidenceStep.GENERATE, "generated")


async def on_scored(message: StreamMessage):
    await _handle(message, EvidenceStep.SCORE, "scored")


async def on_error(message: StreamMessage):
    # any step: the job id says which one
    await _handle(message, None, "error")


AI_RESULT_HANDLERS.update(
    {
        CLASSIFIED: on_classified,
        GENERATED: on_generated,
        SCORED: on_scored,
        AI_ERROR: on_error,
    }
)


# ------------------------------ timeouts ------------------------------ #


async def sweep_timeouts() -> int:
    """Falls back for steps with no result in AI_STEP_TIMEOUT_SECONDS; returns how many"""
    cutoff: datetime = datetime.now(UTC) - timedelta(seconds=SETTINGS.AI_STEP_TIMEOUT_SECONDS)
    handled: int = 0
    async with session_factory() as session:
        uow = UnitOfWorkRepository(session)
        # one at a time: each fallback commits, which releases the row lock
        for _ in range(SWEEP_BATCH):
            stale: list[Dispute] = await uow.repo(DisputeRepository).stale_generating(
                cutoff, limit=1
            )
            if not stale:
                break
            dispute: Dispute = stale[0]
            merchant: Merchant = await uow.repo(MerchantRepository).get_profile(dispute.merchant_id)
            await EvidenceChain(uow, redis_factory()).step_failed(merchant, dispute, "timed out")
            handled += 1
    return handled


async def run_timeout_sweeps():
    """The api's sweep loop, started from the lifespan; errors never end it"""
    while True:
        try:
            await sweep_timeouts()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Evidence timeout sweep failed")
        await asyncio.sleep(SETTINGS.AI_TIMEOUT_SWEEP_SECONDS)
