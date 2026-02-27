"""Unit tests for reasoning tool."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tools.reasoning_tool import ReasoningTool


class TestReasoningTool:
    """Tests for ReasoningTool."""

    def test_name(self):
        """ReasoningTool has correct name."""
        mock_llm = AsyncMock()
        tool = ReasoningTool(llm=mock_llm)
        assert tool.name == "reasoning_tool"

    def test_description(self):
        """ReasoningTool has description."""
        mock_llm = AsyncMock()
        tool = ReasoningTool(llm=mock_llm)
        assert "reasoning" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_calls_llm(self, state_with_analysis, mock_chat_model):
        """ReasoningTool calls LLM with proper messages."""
        mock_chat_model.ainvoke.return_value = type(
            "AIMessage",
            (),
            {
                "content": '{"narrative": "Test", "risk_level": "LOW", "key_findings": [], "hypotheses": [], "confidence": 0.5}',
                "usage_metadata": {"input_tokens": 100, "output_tokens": 50},
            },
        )()
        tool = ReasoningTool(llm=mock_chat_model)
        result = await tool.execute(state_with_analysis)

        mock_chat_model.ainvoke.assert_called_once()
        assert "reasoning" in result
        assert result["reasoning"]["llm_status"] == "success"

    @pytest.mark.asyncio
    async def test_execute_updates_severity(self, state_with_analysis):
        """ReasoningTool updates severity from LLM response."""
        from langchain_core.messages import AIMessage

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content='{"narrative": "High risk", "risk_level": "HIGH", "key_findings": ["Velocity burst"], "hypotheses": [], "confidence": 0.85}'
        )
        tool = ReasoningTool(llm=mock_llm)
        result = await tool.execute(state_with_analysis)

        assert result["severity"] == "HIGH"

    @pytest.mark.asyncio
    async def test_execute_adds_hypotheses(self, state_with_analysis):
        """ReasoningTool adds hypotheses from LLM response."""
        from langchain_core.messages import AIMessage

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content='{"narrative": "Test", "risk_level": "MEDIUM", "key_findings": [], "hypotheses": ["Card testing"], "confidence": 0.6}'
        )
        tool = ReasoningTool(llm=mock_llm)
        result = await tool.execute(state_with_analysis)

        assert "Card testing" in result["hypotheses"]

    @pytest.mark.asyncio
    async def test_execute_handles_llm_error_with_evidence_fallback(self, state_with_analysis):
        """LLM runtime errors keep risk assessment meaningful via evidence fallback."""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("LLM timeout")
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state_with_analysis)

        reasoning = result["reasoning"]
        assert reasoning["llm_status"] == "error"
        assert reasoning["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert str(reasoning["summary"]).startswith("Evidence fallback")
        assert float(reasoning["confidence"]) > 0.0
        assert "error_detail" in reasoning

    @pytest.mark.asyncio
    async def test_execute_handles_llm_stage_timeout_with_evidence_fallback(
        self, state_with_analysis
    ):
        """Slow LLM responses should degrade gracefully without failing the tool execution."""
        mock_llm = AsyncMock()

        async def _slow_response(*args, **kwargs):
            await asyncio.sleep(0.05)
            return type(
                "AIMessage",
                (),
                {
                    "content": '{"narrative":"slow","risk_level":"LOW","key_findings":[],"hypotheses":[],"confidence":0.4}',
                    "usage_metadata": {"input_tokens": 10, "output_tokens": 10},
                },
            )()

        mock_llm.ainvoke.side_effect = _slow_response
        settings = SimpleNamespace(
            llm=SimpleNamespace(
                prompt_guard_enabled=False,
                max_completion_tokens=384,
                stage_timeout_seconds=0.01,
            )
        )
        tool = ReasoningTool(llm=mock_llm, settings=settings)

        result = await tool.execute(state_with_analysis)

        reasoning = result["reasoning"]
        assert reasoning["llm_status"] == "timeout"
        assert reasoning["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert str(reasoning["summary"]).startswith("Evidence fallback")
        assert "error_detail" in reasoning

    @pytest.mark.asyncio
    async def test_execute_handles_parse_error_with_evidence_fallback(self, state_with_analysis):
        """Invalid JSON output should also use evidence fallback risk assessment."""
        from langchain_core.messages import AIMessage

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(content="not valid json")
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state_with_analysis)

        reasoning = result["reasoning"]
        assert reasoning["llm_status"] == "parse_error"
        assert reasoning["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert str(reasoning["summary"]).startswith("Evidence fallback")
        assert float(reasoning["confidence"]) > 0.0

    @pytest.mark.asyncio
    async def test_execute_calibrates_medium_risk_down_for_strong_counter_evidence(
        self, initial_state
    ):
        """LLM MEDIUM should be capped to LOW when only weak signals exist and counter-evidence is strong."""
        from langchain_core.messages import AIMessage

        state = {
            **initial_state,
            "context": {
                "transaction": {
                    "transaction_id": "txn-legit-1",
                    "amount": 250.0,
                    "currency": "USD",
                    "merchant_id": "merchant-legit",
                    "card_id": "card-legit",
                },
                "transaction_context": {
                    "3ds_verified": True,
                    "trusted_device": True,
                    "cardholder_present": True,
                    "is_recurring_customer": True,
                },
                "rule_matches": [{"rule_name": "VELOCITY_SHORT_TERM"}],
            },
            "pattern_results": {
                "scores": [
                    {"pattern_name": "velocity", "score": 0.3, "weight": 1.0, "details": {}}
                ],
                "overall_score": 0.3,
                "patterns_detected": [],
            },
            "similarity_results": {"matches": [], "overall_score": 0.0},
        }

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=(
                '{"narrative":"Moderate concern due velocity",'
                '"risk_level":"MEDIUM","key_findings":["velocity rule"],'
                '"hypotheses":[],"confidence":0.7}'
            )
        )
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state)

        reasoning = result["reasoning"]
        assert result["severity"] == "LOW"
        assert reasoning["llm_risk_level"] == "MEDIUM"
        assert reasoning["severity_calibration"] == "counter_evidence_no_pattern_cap"

    @pytest.mark.asyncio
    async def test_execute_marks_partial_parse_status(self, state_with_analysis):
        """Truncated-but-salvageable JSON should be tracked as partial_parse, not parse_error."""
        from langchain_core.messages import AIMessage

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content='{"narrative":"Likely legitimate repeat activity.","risk_level":"LOW","confidence":0.61'
        )
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state_with_analysis)

        reasoning = result["reasoning"]
        assert reasoning["llm_status"] == "partial_parse"
        assert reasoning["risk_level"] == "LOW"

    @pytest.mark.asyncio
    async def test_execute_caps_medium_with_strong_counter_evidence_and_moderate_similarity(
        self, initial_state
    ):
        """MEDIUM should calibrate down to LOW when counter-evidence is very strong and patterns are weak."""
        from langchain_core.messages import AIMessage

        state = {
            **initial_state,
            "context": {
                "transaction": {
                    "transaction_id": "txn-counter-1",
                    "amount": 180.0,
                    "currency": "USD",
                    "merchant_id": "merchant-legit-2",
                    "card_id": "card-legit-2",
                    "avs_match": True,
                    "cvv_match": True,
                },
                "transaction_context": {
                    "3ds_verified": True,
                    "trusted_device": True,
                    "cardholder_present": True,
                    "is_recurring_customer": True,
                },
                "rule_matches": [],
            },
            "pattern_results": {
                "scores": [
                    {"pattern_name": "velocity", "score": 0.25, "weight": 1.0, "details": {}}
                ],
                "overall_score": 0.25,
                "patterns_detected": [],
            },
            "similarity_results": {
                "matches": [{"transaction_id": "hist-1", "score": 0.63}],
                "overall_score": 0.63,
            },
        }

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=(
                '{"narrative":"Moderate concern due to similarity",'
                '"risk_level":"MEDIUM","key_findings":["similarity moderate"],'
                '"hypotheses":[],"confidence":0.62}'
            )
        )
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state)

        reasoning = result["reasoning"]
        assert result["severity"] == "LOW"
        assert reasoning["llm_risk_level"] == "MEDIUM"
        assert reasoning["severity_calibration"] == "counter_evidence_no_pattern_cap"

    @pytest.mark.asyncio
    async def test_execute_caps_medium_with_three_counter_evidence_signals(self, initial_state):
        """Three strong legitimacy signals should be enough to cap MEDIUM to LOW."""
        from langchain_core.messages import AIMessage

        state = {
            **initial_state,
            "context": {
                "transaction": {
                    "transaction_id": "txn-counter-3",
                    "amount": 79.0,
                    "currency": "USD",
                    "merchant_id": "merchant-legit-3",
                    "card_id": "card-legit-3",
                },
                "transaction_context": {
                    "3ds_verified": True,
                    "trusted_device": True,
                    "cardholder_present": True,
                },
                "rule_matches": [],
            },
            "pattern_results": {
                "scores": [
                    {"pattern_name": "velocity", "score": 0.2, "weight": 1.0, "details": {}}
                ],
                "overall_score": 0.2,
                "patterns_detected": [],
            },
            "similarity_results": {
                "matches": [{"transaction_id": "hist-1", "score": 0.5}],
                "overall_score": 0.5,
            },
        }

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=(
                '{"narrative":"Moderate concern due to moderate similarity",'
                '"risk_level":"MEDIUM","key_findings":["similarity moderate"],'
                '"hypotheses":[],"confidence":0.58}'
            )
        )
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state)

        reasoning = result["reasoning"]
        assert result["severity"] == "LOW"
        assert reasoning["llm_risk_level"] == "MEDIUM"
        assert reasoning["severity_calibration"] == "counter_evidence_no_pattern_cap"

    @pytest.mark.asyncio
    async def test_execute_caps_high_with_strong_counter_evidence(self, initial_state):
        """HIGH should also be capped when counter-evidence is strong and pattern evidence is weak."""
        from langchain_core.messages import AIMessage

        state = {
            **initial_state,
            "context": {
                "transaction": {
                    "transaction_id": "txn-cap-high-1",
                    "amount": 120.0,
                    "currency": "USD",
                    "merchant_id": "merchant-legit-4",
                    "card_id": "card-legit-4",
                    "decision": "DECLINE",
                },
                "transaction_context": {
                    "3ds_verified": True,
                    "trusted_device": True,
                    "cardholder_present": True,
                },
                "rule_matches": [{"rule_name": "VELOCITY_SHORT_TERM"}],
            },
            "pattern_results": {
                "scores": [
                    {"pattern_name": "time_anomaly", "score": 0.3, "weight": 1.0, "details": {}}
                ],
                "overall_score": 0.05,
                "patterns_detected": [],
            },
            "similarity_results": {
                "matches": [{"transaction_id": "hist-1", "score": 0.63}],
                "overall_score": 0.63,
            },
        }

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=(
                '{"narrative":"Declined with moderate similarity and mitigating factors",'
                '"risk_level":"HIGH","key_findings":["moderate similarity"],'
                '"hypotheses":[],"confidence":0.6}'
            )
        )
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state)

        reasoning = result["reasoning"]
        assert result["severity"] == "LOW"
        assert reasoning["llm_risk_level"] == "HIGH"
        assert reasoning["severity_calibration"] == "counter_evidence_no_pattern_cap"

    @pytest.mark.asyncio
    async def test_execute_raises_low_to_medium_for_declined_strong_pattern(self, initial_state):
        """LOW should be elevated when a declined transaction has a strong fraud pattern."""
        from langchain_core.messages import AIMessage

        state = {
            **initial_state,
            "context": {
                "transaction": {
                    "transaction_id": "txn-floor-1",
                    "amount": 250.0,
                    "currency": "USD",
                    "merchant_id": "merchant-risky",
                    "card_id": "card-risky",
                    "decision": "DECLINE",
                },
                "transaction_context": {},
                "rule_matches": [{"rule_name": "CROSS_MERCHANT"}],
            },
            "pattern_results": {
                "scores": [
                    {"pattern_name": "cross_merchant", "score": 0.8, "weight": 1.0, "details": {}}
                ],
                "overall_score": 0.42,
                "patterns_detected": ["cross_merchant"],
            },
            "similarity_results": {
                "matches": [{"transaction_id": "hist-1", "score": 0.55}],
                "overall_score": 0.55,
            },
        }

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=(
                '{"narrative":"Risk appears low with some mitigation",'
                '"risk_level":"LOW","key_findings":["counter evidence"],'
                '"hypotheses":[],"confidence":0.55}'
            )
        )
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state)

        reasoning = result["reasoning"]
        assert result["severity"] == "MEDIUM"
        assert reasoning["llm_risk_level"] == "LOW"
        assert reasoning["severity_calibration"] == "counter_evidence_no_pattern_cap"

    @pytest.mark.asyncio
    async def test_execute_raises_low_to_medium_for_high_decline_velocity_combo(
        self, initial_state
    ):
        """LOW should be elevated when decline+velocity/card-testing signals are jointly strong."""
        from langchain_core.messages import AIMessage

        state = {
            **initial_state,
            "context": {
                "transaction": {
                    "transaction_id": "txn-floor-2",
                    "amount": 325.0,
                    "currency": "USD",
                    "merchant_id": "merchant-decline",
                    "card_id": "card-decline",
                    "decision": "APPROVE",
                },
                "transaction_context": {},
                "rule_matches": [],
            },
            "pattern_results": {
                "scores": [
                    {"pattern_name": "velocity", "score": 0.7, "weight": 0.4, "details": {}},
                    {"pattern_name": "decline_anomaly", "score": 0.9, "weight": 0.3, "details": {}},
                    {"pattern_name": "card_testing", "score": 0.7, "weight": 0.35, "details": {}},
                ],
                "overall_score": 0.40,
                "patterns_detected": ["velocity", "decline_anomaly", "card_testing"],
            },
            "similarity_results": {
                "matches": [],
                "overall_score": 0.1,
            },
        }

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=(
                '{"narrative":"High velocity but strong counter evidence; risk likely low.",'
                '"risk_level":"LOW","key_findings":["velocity spike"],'
                '"hypotheses":[],"confidence":0.55}'
            )
        )
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state)

        reasoning = result["reasoning"]
        assert result["severity"] == "MEDIUM"
        assert reasoning["llm_risk_level"] == "LOW"
        assert reasoning["severity_calibration"] == "counter_evidence_no_pattern_cap"

    @pytest.mark.asyncio
    async def test_execute_rewrites_low_risk_language_for_medium_severity(self, initial_state):
        """Medium severity output should not retain explicit low-risk/no-pattern phrasing."""
        from langchain_core.messages import AIMessage

        state = {
            **initial_state,
            "context": {
                "transaction": {
                    "transaction_id": "txn-text-1",
                    "amount": 1500.0,
                    "currency": "USD",
                    "merchant_id": "merchant-high-amt",
                    "card_id": "card-high-amt",
                    "decision": "APPROVE",
                },
                "transaction_context": {},
                "rule_matches": [],
            },
            "pattern_results": {
                "scores": [
                    {"pattern_name": "amount_anomaly", "score": 0.8, "weight": 1.0, "details": {}}
                ],
                "overall_score": 0.38,
                "patterns_detected": ["amount_anomaly"],
            },
            "similarity_results": {
                "matches": [{"transaction_id": "hist-1", "score": 0.62}],
                "overall_score": 0.62,
            },
        }

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=(
                '{"narrative":"High amount but no patterns detected; low risk due similar behavior.",'
                '"risk_level":"MEDIUM","key_findings":["amount high"],'
                '"hypotheses":[],"confidence":0.6}'
            )
        )
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state)

        reasoning = result["reasoning"]
        summary = str(reasoning.get("summary", "")).lower()
        assert result["severity"] == "MEDIUM"
        assert "no patterns detected" not in summary
        assert "low risk" not in summary

    @pytest.mark.asyncio
    async def test_execute_caps_medium_when_similarity_counter_evidence_present_for_approved_flow(
        self, initial_state
    ):
        """Approved low-signal flow should cap MEDIUM when similarity counter-evidence exists."""
        from langchain_core.messages import AIMessage

        state = {
            **initial_state,
            "context": {
                "transaction": {
                    "transaction_id": "txn-sim-counter-1",
                    "amount": 50.0,
                    "currency": "USD",
                    "merchant_id": "merchant-unknown",
                    "card_id": "card-unknown",
                    "decision": "APPROVE",
                },
                "transaction_context": {},
                "rule_matches": [],
            },
            "pattern_results": {
                "scores": [
                    {"pattern_name": "time_anomaly", "score": 0.4, "weight": 1.0, "details": {}}
                ],
                "overall_score": 0.05,
                "patterns_detected": [],
            },
            "similarity_results": {
                "matches": [
                    {
                        "transaction_id": "hist-1",
                        "score": 0.54,
                        "counter_evidence": [{"type": "3ds_success", "strength": 0.8}],
                    }
                ],
                "overall_score": 0.54,
            },
        }

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=(
                '{"narrative":"Approved transaction with moderate similarity and limited profile data",'
                '"risk_level":"MEDIUM","key_findings":[],"hypotheses":[],"confidence":0.6}'
            )
        )
        tool = ReasoningTool(llm=mock_llm)

        result = await tool.execute(state)

        reasoning = result["reasoning"]
        assert result["severity"] == "LOW"
        assert reasoning["llm_risk_level"] == "MEDIUM"
        assert reasoning["severity_calibration"] == "counter_evidence_no_pattern_cap"
