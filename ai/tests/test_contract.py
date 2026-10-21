"""The backend <-> ai contract. The job payloads below are shaped exactly as the backend
builds them (backend/app/api/services/dispute_ai.py, evidence_document.ai_context and
backend/app/worker/services/trust.py), and each result must carry the keys the backend's
handlers read (dispute_ai.EvidenceChain and trust_ai). Change both sides together."""

import json
from dataclasses import replace

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from src.config import Settings
from src.handlers import build_handlers
from src.handlers.classifier import handle_classify
from src.handlers.evidence_generator import handle_generate_evidence
from src.handlers.quality_scorer import handle_score_quality
from src.handlers.trust_explainer import handle_trust_explain
from src.handlers.trust_recommender import handle_trust_recommend
from src.handlers.trust_state_change import handle_trust_state_change
from src.prompts.loader import load_prompt
from src.schemas.dispute import (
    ClassifierOutput,
    DimensionScores,
    EvidenceOutput,
    ScorerOutput,
)
from src.schemas.enums import DisputeCategory, SubmissionFlow
from src.schemas.trust import (
    TrustExplainOutput,
    TrustRecommendation,
    TrustRecommendOutput,
    TrustStateChangeOutput,
)
from src.streams import AiResultPublisher, StreamMessage

# the evidence item names the backend uses (dispute_ai._available_items)
EVIDENCE_ITEMS: tuple[str, ...] = (
    "transaction_receipt",
    "order_details",
    "fulfillment_record",
    "tracking_number",
    "signed_confirmation",
    "delivery_photo",
    "supporting_documents",
    "customer_history",
)

CLASSIFY_PAYLOAD: dict = {
    "disputeId": "d-1",
    # null when paystack sent no message
    "messagesBody": None,
    "paystackCategory": "chargeback",
    "transactionChannel": "card",
    "hasEvidenceObject": False,
}

GENERATE_PAYLOAD: dict = {
    "disputeId": "d-1",
    "category": "chargeback_no_value",
    "submissionFlow": "chargeback_flow",
    "reason": "Customer complained about debit without value",
    "dueAt": "2026-10-22T18:00:00+00:00",
    "transaction": {
        "paid_at": "2026-10-10T12:00:00Z",
        "amount": 4500000,
        "currency": "NGN",
        "channel": "card",
        "reference": "v3mjfgbnc19v97x",
        "customer_email": "john@example.com",
        "customer_name": "John Doe",
    },
    "order": {
        "order_number": "A-1",
        "description": "Blue sneakers",
        "created_at": "2026-10-09T12:00:00Z",
        "amount": 4500000,
        "currency": "NGN",
    },
    "fulfillment": [
        {
            "type": "delivery",
            "delivery_date": "2026-10-11T09:00:00Z",
            "tracking_number": "GIG-0012",
            "recipient_name": "John Doe",
            "delivery_address": "3a Ladoke Street",
            "notes": None,
            "photos": [
                {
                    "file_id": "11111111-1111-1111-1111-111111111111",
                    "file_name": "door.jpg",
                    "caption": "Parcel at the door",
                    "source": "fulfillment",
                }
            ],
        }
    ],
    "customerHistory": {"payment_count": 4, "first_payment_at": None, "prior_disputes": 0},
    "supportingDocuments": [],
    "evidenceStrategy": ["fulfillment_record", "delivery_photo"],
    "specialInstructions": None,
    "reconciliationStatus": {
        "status": "auto_matched",
        "tier": 1,
        "confidence": 100,
        "reconciled_at": "2026-10-10T12:05:00Z",
    },
}

SCORE_PAYLOAD: dict = {
    "disputeId": "d-1",
    "narrative": "On 10 October 2026 John Doe paid NGN 45,000.00 ...",
    "category": "chargeback_no_value",
    "availableEvidenceItems": ["transaction_receipt", "order_details", "fulfillment_record"],
    "evidenceItemsReferenced": ["transaction_receipt"],
}

EXPLAIN_PAYLOAD: dict = {
    "merchantId": "m-1",
    "currentState": "building",
    "signals": {
        "reconciliation_rate": 85.0,
        "fulfillment_rate": 55.0,
        "dispute_rate": 1.0,
        # null: nothing to measure yet
        "dispute_win_rate": None,
        "avg_response_time": None,
        "evidence_readiness": 62.5,
    },
    "sample": {"payments_30d": 40, "days_on_platform": 60},
    "policyThresholds": {
        "verified": {"reconciliation_rate": "at least 80%", "fulfillment_rate": "at least 70%"},
        "building": {"reconciliation_rate": "at least 50%"},
        "review_when_any": {"dispute_rate": "above 5%"},
        "minimum_sample": {"payments_30d": "at least 10", "days_on_platform": "at least 14"},
    },
}

STATE_CHANGE_PAYLOAD: dict = {
    "merchantId": "m-1",
    "previousState": "verified",
    "newState": "building",
    "signalDiff": {"dispute_win_rate": {"before": None, "after": 0.0}},
}


class FakeClient:
    def __init__(self, output):
        self.output = output
        self.calls: list[tuple] = []

    async def complete(self, task, system_prompt, user_prompt, output_model):
        self.calls.append((task, system_prompt, user_prompt, output_model))
        return self.output


def _message(event: str, payload: dict, job_id: str = "job-1") -> StreamMessage:
    return StreamMessage(
        id="1-0",
        event=event,
        job_id=job_id,
        version="1",
        payload=payload,
        created_at="2026-10-21T10:00:00+00:00",
        deliveries=1,
    )


@pytest_asyncio.fixture
async def publisher():
    redis = FakeAsyncRedis(decode_responses=True)
    yield AiResultPublisher(redis, replace(Settings(), AI_RESULT_STREAM="test:results")), redis
    await redis.aclose()


async def _published(redis) -> tuple[str, str, dict]:
    ((_, fields),) = await redis.xrange("test:results")
    return fields["event"], fields["job_id"], json.loads(fields["payload"])


@pytest.mark.asyncio
async def test_classify(publisher):
    result_publisher, redis = publisher
    client = FakeClient(
        ClassifierOutput(
            category=DisputeCategory.UNKNOWN,
            confidence=0.2,
            submission_flow=SubmissionFlow.CHARGEBACK_FLOW,
            evidence_strategy=["transaction_receipt"],
            special_instructions=None,
        )
    )

    await handle_classify(
        _message("ai:dispute:classify", CLASSIFY_PAYLOAD), client, result_publisher
    )

    event, job_id, payload = await _published(redis)
    # dispute_ai.on_classified reads these
    assert (event, job_id) == ("ai:result:classified", "job-1")
    assert payload["disputeId"] == "d-1"
    assert {"category", "confidence", "submissionFlow", "evidenceStrategy"} <= set(payload)


@pytest.mark.asyncio
async def test_generate_evidence(publisher):
    result_publisher, redis = publisher
    client = FakeClient(
        EvidenceOutput(
            narrative="On 10 October 2026 John Doe paid NGN 45,000.00 by card.",
            conclusion="The merchant requests resolution in its favour.",
            missing_evidence=[],
            evidence_items_referenced=["transaction_receipt", "delivery_photo"],
        )
    )

    await handle_generate_evidence(
        _message("ai:dispute:generate-evidence", GENERATE_PAYLOAD), client, result_publisher
    )

    event, job_id, payload = await _published(redis)
    assert (event, job_id) == ("ai:result:evidence-generated", "job-1")
    # dispute_ai.on_generated reads these
    assert set(payload) >= {"disputeId", "narrative", "conclusion", "missingEvidence"}
    assert payload["evidenceItemsReferenced"] == ["transaction_receipt", "delivery_photo"]
    # the whole package reached the model, including the match
    user_prompt: str = client.calls[0][2]
    assert '"reconciliationStatus"' in user_prompt and "Parcel at the door" in user_prompt


@pytest.mark.asyncio
async def test_score_quality(publisher):
    result_publisher, redis = publisher
    client = FakeClient(
        ScorerOutput(
            overall_score=72,
            dimension_scores=DimensionScores(
                completeness=70, evidence_strength=72.5, formatting=90, customer_context=100
            ),
            suggestions=["Add a delivery photo"],
            ready_to_submit=False,
        )
    )

    await handle_score_quality(
        _message("ai:dispute:score-quality", SCORE_PAYLOAD), client, result_publisher
    )

    event, _, payload = await _published(redis)
    assert event == "ai:result:quality-scored"
    # dispute_ai.on_scored reads these (and rounds the dimension scores)
    assert payload["overallScore"] == 72
    assert set(payload["dimensionScores"]) == {
        "completeness",
        "evidence_strength",
        "formatting",
        "customer_context",
    }
    assert payload["readyToSubmit"] is False


@pytest.mark.asyncio
async def test_trust_explain(publisher):
    result_publisher, redis = publisher
    client = FakeClient(
        TrustExplainOutput(
            explanation="You are Building: fulfillment is at 55%; verified needs 70%.",
            recommendations=[
                TrustRecommendation(
                    action="Log fulfillment with a photo for paid orders",
                    impact_description="Fulfillment is at 55%; verified needs 70%",
                    affected_signal="fulfillment_rate",
                )
            ],
        )
    )

    await handle_trust_explain(
        _message("ai:trust:explain", EXPLAIN_PAYLOAD, "explain-7"), client, result_publisher
    )

    event, job_id, payload = await _published(redis)
    # trust_ai.on_trust_explained matches the job id the profile waits on
    assert (event, job_id) == ("ai:result:trust-explained", "explain-7")
    assert payload["merchantId"] == "m-1"
    # nested actions keep snake_case keys: trust_ai._actions reads exactly these
    assert payload["recommendations"] == [
        {
            "action": "Log fulfillment with a photo for paid orders",
            "impact_description": "Fulfillment is at 55%; verified needs 70%",
            "affected_signal": "fulfillment_rate",
        }
    ]
    # the sample reached the model
    assert '"payments_30d": 40' in client.calls[0][2]


@pytest.mark.asyncio
async def test_trust_state_change_keeps_the_snapshot_job_id(publisher):
    result_publisher, redis = publisher
    client = FakeClient(TrustStateChangeOutput(summary="You moved from Verified to Building."))

    await handle_trust_state_change(
        _message("ai:trust:state-change", STATE_CHANGE_PAYLOAD, "0b8f-snapshot"),
        client,
        result_publisher,
    )

    event, job_id, payload = await _published(redis)
    # trust_ai.on_state_change_summarized finds the snapshot by the job id
    assert (event, job_id) == ("ai:result:state-change-summarized", "0b8f-snapshot")
    assert payload == {
        "jobId": "0b8f-snapshot",
        "merchantId": "m-1",
        "summary": "You moved from Verified to Building.",
    }


@pytest.mark.asyncio
async def test_each_trust_task_has_its_own_prompt(publisher):
    result_publisher, _ = publisher
    recommend = FakeClient(TrustRecommendOutput(explanation=None, recommendations=[]))
    change = FakeClient(TrustStateChangeOutput(summary="x"))

    await handle_trust_recommend(
        _message(
            "ai:trust:recommend",
            {"merchantId": "m-1", "weakestSignals": ["fulfillment_rate"], "recentTrends": {}},
        ),
        recommend,
        result_publisher,
    )
    await handle_trust_state_change(
        _message("ai:trust:state-change", STATE_CHANGE_PAYLOAD), change, result_publisher
    )

    assert recommend.calls[0][1] == load_prompt("trust_recommender")
    assert change.calls[0][1] == load_prompt("trust_state_change")


def test_every_handled_event_has_a_prompt():
    handlers = build_handlers(FakeAsyncRedis(), Settings())
    assert set(handlers) == {
        "ai:dispute:classify",
        "ai:dispute:generate-evidence",
        "ai:dispute:score-quality",
        "ai:trust:explain",
        "ai:trust:recommend",
        "ai:trust:state-change",
    }
    for name in (
        "classifier",
        "evidence",
        "scorer",
        "trust_explainer",
        "trust_recommender",
        "trust_state_change",
    ):
        assert load_prompt(name)


def test_prompts_use_the_backends_evidence_item_names():
    for name in ("classifier", "evidence", "scorer"):
        prompt: str = load_prompt(name)
        for item in EVIDENCE_ITEMS:
            assert item in prompt, f"{name} is missing {item}"


def test_evidence_prompt_explains_minor_units():
    prompt: str = load_prompt("evidence")
    assert "minor unit" in prompt and "NGN 45,000.00" in prompt
