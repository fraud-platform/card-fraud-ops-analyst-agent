"""Unit tests for investigation service."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, ValidationError
from app.services.investigation_service import InvestigationService


@pytest.mark.asyncio
async def test_run_investigation_success():
    """Test running an investigation successfully."""
    mock_session = AsyncMock()
    service = InvestigationService(mock_session)

    mock_run = {
        "run_id": "run-123",
        "transaction_id": "txn-123",
        "status": "SUCCESS",
    }

    mock_pipeline_result = {
        "insight": {
            "insight_id": "insight-1",
            "severity": "HIGH",
            "evidence": [{"type": "pattern", "summary": "High velocity"}],
        },
        "recommendations": [
            {"recommendation_id": "rec-1", "type": "rule_candidate", "severity": "HIGH"}
        ],
    }

    service.run_repo.create = AsyncMock(return_value=mock_run)
    service.pipeline.run = AsyncMock(return_value=mock_pipeline_result)

    result = await service.run_investigation(mode="deterministic", transaction_id="txn-123")

    print("\n[INVESTIGATION_SERVICE] Input:")
    print("  mode: deterministic")
    print("  transaction_id: txn-123")
    print("[INVESTIGATION_SERVICE] Output:")
    print(f"  {json.dumps(result, indent=2, default=str)}")

    assert result["insight"]["insight_id"] == "insight-1"
    assert len(result["recommendations"]) == 1
    service.run_repo.create.assert_called_once()
    service.pipeline.run.assert_called_once()
    mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_run_investigation_with_case_id():
    """Test running an investigation with a case ID."""
    mock_session = AsyncMock()
    service = InvestigationService(mock_session)

    mock_run = {
        "run_id": "run-456",
        "transaction_id": "txn-456",
        "case_id": "case-123",
        "status": "SUCCESS",
    }

    mock_pipeline_result = {
        "insight": {
            "insight_id": "insight-2",
            "severity": "CRITICAL",
            "evidence": [],
        },
        "recommendations": [],
    }

    service.run_repo.create = AsyncMock(return_value=mock_run)
    service.pipeline.run = AsyncMock(return_value=mock_pipeline_result)

    result = await service.run_investigation(
        mode="deterministic", transaction_id="txn-456", case_id="case-123"
    )

    print("\n[INVESTIGATION_SERVICE] Input:")
    print("  mode: deterministic")
    print("  transaction_id: txn-456")
    print("  case_id: case-123")
    print("[INVESTIGATION_SERVICE] Output:")
    print(f"  {json.dumps(result, indent=2, default=str)}")

    assert result["insight"]["severity"] == "CRITICAL"
    service.run_repo.create.assert_called_once()
    mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_run_investigation_feature_disabled():
    """Test that investigation fails when feature flag is disabled."""
    mock_session = AsyncMock()
    service = InvestigationService(mock_session)

    with patch("app.services.investigation_service.get_settings") as mock_settings:
        mock_settings.return_value.features.enable_deterministic_pipeline = False

        with pytest.raises(ValidationError) as exc_info:
            await service.run_investigation(mode="deterministic", transaction_id="txn-123")

        print(f"\n[INVESTIGATION_SERVICE] Expected error: {exc_info.value}")
        assert "Deterministic pipeline is not enabled" in str(exc_info.value)


@pytest.mark.asyncio
async def test_run_investigation_duplicate_triggers_conflict_with_rollback():
    """Test that duplicate trigger_ref raises ConflictError after session rollback.

    Regression test for: session was in FAILED state after IntegrityError, causing
    get_by_trigger_ref() to fail with InvalidRequestError instead of returning ConflictError.
    """
    mock_session = AsyncMock()
    service = InvestigationService(mock_session)

    existing_run = {
        "run_id": "existing-run-123",
        "status": "SUCCESS",
        "trigger_ref": "transaction:txn-dup",
    }

    # Simulate duplicate key violation
    service.run_repo.create = AsyncMock(side_effect=IntegrityError(None, None, None))
    service.run_repo.get_by_trigger_ref = AsyncMock(return_value=existing_run)

    with pytest.raises(ConflictError) as exc_info:
        await service.run_investigation(mode="deterministic", transaction_id="txn-dup")

    # Session must be rolled back before the SELECT query
    mock_session.rollback.assert_called_once()
    service.run_repo.get_by_trigger_ref.assert_called_once()
    assert exc_info.value.details["run_id"] == "existing-run-123"


@pytest.mark.asyncio
async def test_get_investigation():
    """Test getting an investigation by run ID."""
    mock_session = AsyncMock()
    service = InvestigationService(mock_session)

    mock_run = {
        "run_id": "run-789",
        "status": "SUCCESS",
        "mode": "deterministic",
        "trigger_ref": "transaction:txn-789",
        "started_at": "2026-02-15T10:00:00Z",
        "completed_at": "2026-02-15T10:01:00Z",
    }

    mock_insight = {
        "insight_id": "insight-3",
        "generated_at": "2026-02-15T10:00:30Z",
        "evidence": [{"type": "pattern"}],
    }

    mock_recommendations = [
        {
            "recommendation_id": "rec-3",
            "insight_id": "insight-3",
            "type": "rule_candidate",
        }
    ]

    service.run_repo.get = AsyncMock(return_value=mock_run)
    service.insight_repo.get_insights_with_evidence = AsyncMock(return_value=[mock_insight])
    service.recommendation_repo.list_by_insight_id = AsyncMock(return_value=mock_recommendations)

    result = await service.get_investigation("run-789")

    print("\n[INVESTIGATION_SERVICE] Input run_id: run-789")
    print("[INVESTIGATION_SERVICE] Output:")
    print(f"  {json.dumps(result, indent=2, default=str)}")

    assert result["run_id"] == "run-789"
    assert result["status"] == "SUCCESS"
    assert result["transaction_id"] == "txn-789"
    assert result["insight"]["insight_id"] == "insight-3"
    assert len(result["recommendations"]) == 1


@pytest.mark.asyncio
async def test_get_investigation_not_found():
    """Test getting an investigation that doesn't exist."""
    mock_session = AsyncMock()
    service = InvestigationService(mock_session)

    service.run_repo.get = AsyncMock(return_value=None)

    result = await service.get_investigation("run-999")

    print("\n[INVESTIGATION_SERVICE] Input run_id: run-999")
    print(f"[INVESTIGATION_SERVICE] Output: {result}")

    assert result is None


@pytest.mark.asyncio
async def test_get_investigation_rehydrates_pattern_and_similarity_for_action_plan():
    """Detail response should reconstruct stage inputs from stored evidence envelopes."""
    mock_session = AsyncMock()
    service = InvestigationService(mock_session)

    mock_run = {
        "run_id": "run-rehydrate",
        "status": "SUCCESS",
        "mode": "deterministic",
        "trigger_ref": "transaction:txn-rehydrate",
        "started_at": "2026-02-15T10:00:00Z",
        "completed_at": "2026-02-15T10:01:00Z",
        "stage_durations": {"pattern_analysis": 12.4, "similarity_analysis": 15.8},
        "llm_status": "disabled",
    }
    mock_insight = {
        "insight_id": "insight-rehydrate",
        "generated_at": "2026-02-15T10:00:30Z",
        "severity": "HIGH",
        "model_mode": "deterministic",
        "evidence": [
            {
                "evidence_id": "ev-pattern",
                "evidence_kind": "pattern",
                "evidence_payload": {
                    "evidence_kind": "pattern",
                    "category": "velocity",
                    "strength": 0.83,
                    "supporting_data": {"details": {"burst_1h": 7}},
                },
            },
            {
                "evidence_id": "ev-sim",
                "evidence_kind": "similarity",
                "evidence_payload": {
                    "evidence_kind": "similarity",
                    "category": "vector",
                    "strength": 0.72,
                    "supporting_data": {
                        "match_id": "txn-old-1",
                        "match_type": "vector",
                        "similarity_score": 0.72,
                        "details": {"same_card": True},
                    },
                },
            },
        ],
    }

    service.run_repo.get = AsyncMock(return_value=mock_run)
    service.insight_repo.get_insights_with_evidence = AsyncMock(return_value=[mock_insight])
    service.recommendation_repo.list_by_insight_id = AsyncMock(return_value=[])

    result = await service.get_investigation("run-rehydrate")

    actions = result.get("action_plan", [])
    evidence_refs = {
        str(action.get("evidence_ref")) for action in actions if isinstance(action, dict)
    }
    assert "pattern:velocity" in evidence_refs
    assert "similarity" in evidence_refs
    assert (
        result["agentic_trace"]["stages"]["similarity_analysis"]["metadata"]["vector_match_count"]
        == 1
    )


@pytest.mark.asyncio
async def test_get_investigation_with_case():
    """Test getting an investigation with case ID."""
    mock_session = AsyncMock()
    service = InvestigationService(mock_session)

    mock_run = {
        "run_id": "run-case",
        "status": "SUCCESS",
        "mode": "deterministic",
        "trigger_ref": "transaction:txn-case case:case-456",
        "started_at": "2026-02-15T10:00:00Z",
        "completed_at": "2026-02-15T10:01:00Z",
    }

    service.run_repo.get = AsyncMock(return_value=mock_run)
    service.insight_repo.get_insights_with_evidence = AsyncMock(return_value=[])
    service.recommendation_repo.list_by_insight_id = AsyncMock(return_value=[])

    result = await service.get_investigation("run-case")

    print("\n[INVESTIGATION_SERVICE] Input run_id: run-case")
    print("[INVESTIGATION_SERVICE] Output:")
    print(f"  {json.dumps(result, indent=2, default=str)}")

    assert result["transaction_id"] == "txn-case"
    assert result["case_id"] == "case-456"


@pytest.mark.asyncio
async def test_get_investigation_vector_stage_with_zero_matches_adds_gap():
    """Detail responses should report vector no-match gaps when similarity stage ran."""
    mock_session = AsyncMock()
    service = InvestigationService(mock_session)

    mock_run = {
        "run_id": "run-vector-gap",
        "status": "SUCCESS",
        "mode": "deterministic",
        "trigger_ref": "transaction:txn-vector-gap",
        "started_at": "2026-02-15T10:00:00Z",
        "completed_at": "2026-02-15T10:01:00Z",
        "stage_durations": {"context_build": 8.1, "similarity_analysis": 12.2},
        "llm_status": "success",
        "runtime_feature_flags": {
            "vector_search_enabled": True,
            "enable_llm_reasoning": True,
            "enforce_human_approval": True,
        },
        "runtime_safeguards": {
            "human_approval_enforced": True,
            "prompt_guard_enabled": True,
            "consistency_check_enabled": True,
            "vector_fail_closed": True,
        },
    }
    mock_insight = {
        "insight_id": "insight-vector-gap",
        "generated_at": "2026-02-15T10:00:30Z",
        "severity": "LOW",
        "model_mode": "hybrid",
        "evidence": [
            {
                "evidence_id": "ev-context",
                "evidence_kind": "context_snapshot",
                "evidence_payload": {
                    "evidence_kind": "context_snapshot",
                    "supporting_data": {
                        "transaction_context": {"3ds_verified": True, "device_trusted": True},
                        "velocity_snapshot": {"count_1h": 1},
                        "card_history": [{"transaction_id": "txn-older"}],
                    },
                },
            }
        ],
    }

    service.run_repo.get = AsyncMock(return_value=mock_run)
    service.insight_repo.get_insights_with_evidence = AsyncMock(return_value=[mock_insight])
    service.recommendation_repo.list_by_insight_id = AsyncMock(return_value=[])

    result = await service.get_investigation("run-vector-gap")

    assert (
        "Vector search returned no close historical matches in active window."
        in result["evidence_gaps"]
    )
    assert result["agentic_trace"]["stages"]["similarity_analysis"]["status"] == "success"
    assert (
        result["agentic_trace"]["stages"]["similarity_analysis"]["metadata"][
            "vector_stage_executed"
        ]
        is True
    )
    assert (
        result["agentic_trace"]["stages"]["similarity_analysis"]["metadata"]["vector_match_count"]
        == 0
    )


def test_build_agentic_trace_safeguards_follow_config_flags():
    """Agentic safeguards should reflect actual runtime configuration flags."""
    trace = InvestigationService._build_agentic_trace(
        run={
            "run_id": "run-guardrails",
            "llm_status": "disabled",
            "stage_durations": {"context_build": 5.0},
        },
        recommendations=[],
        evidence=[],
        runtime_feature_flags={
            "enable_llm_reasoning": False,
            "vector_search_enabled": False,
            "enforce_human_approval": False,
        },
        runtime_safeguards={
            "human_approval_enforced": False,
            "prompt_guard_enabled": False,
            "consistency_check_enabled": False,
            "vector_fail_closed": False,
        },
    )

    assert trace["safeguards"] == {
        "human_approval_enforced": False,
        "prompt_guard_enabled": False,
        "consistency_check_enabled": False,
        "vector_fail_closed": False,
    }
