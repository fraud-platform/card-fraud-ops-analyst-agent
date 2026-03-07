"""Planner node - LLM-driven tool selection."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from opentelemetry import trace

from app.agent.state import InvestigationState, PlannerDecision
from app.core.config import get_settings
from app.core.errors import PlannerError
from app.core.metrics import (
    ops_agent_llm_calls_total,
    ops_agent_llm_latency_seconds,
    ops_agent_llm_tokens_total,
    ops_agent_planner_decisions_total,
)
from app.utils.clock import utc_now

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from app.agent.registry import ToolRegistry

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


PLANNER_SYSTEM_PROMPT = """You are a fraud investigation planner for a card fraud operations team.
Your job is to determine the NEXT investigation step based on current evidence.

You must respond with a JSON object: {"tool": "<name>", "reason": "<why>", "confidence": <0.0-1.0>}
Or to finish: {"tool": "COMPLETE", "reason": "<why>", "confidence": <0.0-1.0>}

Only output the JSON object, no additional text.
"""

PLANNER_USER_TEMPLATE = """## Current Investigation State

Transaction ID: {transaction_id}
Completed Steps: {completed_steps}
Step Count: {step_count} / {max_steps}

### Evidence Collected
- Context Available: {has_context}
- Pattern Analysis Done: {has_patterns}
- Similarity Analysis Done: {has_similarity}
- Link Analysis Done: {has_link_analysis}
- Reasoning Done: {has_reasoning}
- Recommendations Generated: {has_recommendations}
- Rule Draft Generated: {has_rule_draft}
- Current Confidence: {confidence_score}
- Current Severity: {severity}
- Findings Summary: {findings_summary}

## Available Tools
{tool_descriptions}

## Rules
1. ALWAYS retrieve context first if not yet available.
2. Run analysis tools (pattern_tool, similarity_tool, link_analysis_tool) BEFORE reasoning_tool.
3. Run reasoning_tool BEFORE recommendation_tool.
4. Run recommendation_tool BEFORE rule_draft_tool.
5. NEVER repeat a tool that is already in completed_steps.
6. Output COMPLETE when recommendations have been generated and the investigation has sufficient evidence.
7. If confidence is above 0.8 and recommendations exist, prefer COMPLETE over additional tools.

## Decision
Select the next tool to execute, or COMPLETE if the investigation is sufficient.
"""

PLANNER_MAX_DECISION_REPAIRS = 2

PLANNER_RESPONSE_FORMAT = {
    "type": "object",
    "properties": {
        "tool": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["tool", "reason", "confidence"],
}


async def planner_node(
    state: InvestigationState,
    llm: BaseChatModel,
    registry: ToolRegistry,
) -> InvestigationState:
    """Analyze state and select next investigation tool using LLM."""
    with tracer.start_as_current_span("agent.planner") as span:
        span.set_attribute("investigation_id", state["investigation_id"])
        span.set_attribute("step_count", state["step_count"])
        if state.get("transaction_id"):
            span.set_attribute("transaction_id", state["transaction_id"])
        model_mode = state.get("model_mode", "unknown")
        span.set_attribute("model_mode", model_mode)
        if state.get("case_id"):
            span.set_attribute("case_id", state["case_id"])
        if state.get("scenario_name"):
            span.set_attribute("scenario_name", state["scenario_name"])

        has_context = bool(state.get("context"))
        valid_tools = set(registry.tool_names) | {"COMPLETE"} if registry else {"COMPLETE"}
        settings = get_settings()
        feature_flags = state.get("feature_flags", {})
        planner_llm_enabled = bool(
            settings.planner.llm_enabled and feature_flags.get("planner_llm_enabled", True)
        )
        planner_circuit_open = _planner_llm_circuit_open(state)

        llm_prompt_preview = None
        llm_response_preview = None

        if not has_context and "context_tool" not in state["completed_steps"]:
            tool_name = "context_tool"
            reason = "Context is required before any analysis"
            confidence = 0.99
        elif not planner_llm_enabled:
            tool_name, reason, confidence = _rule_sequence_next_tool(state, registry)
        elif planner_circuit_open:
            logger.warning(
                "Planner circuit open — falling back to rule-sequence",
                investigation_id=state["investigation_id"],
            )
            tool_name, reason, confidence = _rule_sequence_next_tool(state, registry)
        else:
            try:
                (
                    tool_name,
                    reason,
                    confidence,
                    llm_prompt_preview,
                    llm_response_preview,
                ) = await _llm_planning(state, llm, registry)
            except PlannerError as exc:
                logger.warning(
                    "Planner LLM failed — falling back to rule-sequence",
                    investigation_id=state["investigation_id"],
                    llm_error=str(exc),
                )
                tool_name, reason, confidence = _rule_sequence_next_tool(state, registry)

        if tool_name not in valid_tools:
            raise PlannerError(
                f"Planner selected invalid tool '{tool_name}'. Valid tools: {valid_tools}",
                investigation_id=state["investigation_id"],
                tool_name=tool_name,
            )

        decision: PlannerDecision = {
            "step": state["step_count"] + 1,
            "selected_tool": tool_name,
            "reason": reason,
            "confidence": confidence,
            "timestamp": utc_now().isoformat(),
            "llm_prompt_preview": llm_prompt_preview[:1000] if llm_prompt_preview else None,
            "llm_response_preview": llm_response_preview[:500] if llm_response_preview else None,
        }

        ops_agent_planner_decisions_total.labels(selected_tool=tool_name).inc()

        span.set_attribute("selected_tool", tool_name)
        span.set_attribute("confidence", confidence)

        logger.info(
            "Planner decision",
            investigation_id=state["investigation_id"],
            step=state["step_count"] + 1,
            selected_tool=tool_name,
            reason=reason,
            confidence=confidence,
        )

        return {
            **state,
            "next_action": tool_name,
            "step_count": state["step_count"] + 1,
            "planner_decisions": [*state["planner_decisions"], decision],
        }


async def _llm_planning(
    state: InvestigationState,
    llm: BaseChatModel,
    registry: ToolRegistry,
) -> tuple[str, str, float, str | None, str | None]:
    """Call LLM for planning decision. Raises PlannerError on failure."""
    tool_descriptions = "\n".join(
        f"- {t['name']}: {t['description']}" for t in registry.list_tools()
    )

    # SECURITY: state values are produced by internal investigation flow, not direct user input.
    # Transaction context is sourced from authenticated TM service calls and controlled tool outputs.
    user_prompt = PLANNER_USER_TEMPLATE.format(
        transaction_id=state["transaction_id"],
        completed_steps=", ".join(state["completed_steps"]) or "none",
        step_count=state["step_count"],
        max_steps=state["max_steps"],
        has_context=bool(state.get("context")),
        has_patterns=bool(state.get("pattern_results")),
        has_similarity=bool(state.get("similarity_results")),
        has_link_analysis=bool(state.get("link_analysis_results")),
        has_reasoning=bool(state.get("reasoning")),
        has_recommendations=bool(state.get("recommendations")),
        has_rule_draft=state.get("rule_draft") is not None,
        confidence_score=state.get("confidence_score", 0.0),
        severity=state.get("severity", "LOW"),
        findings_summary=_build_findings_summary(state),
        tool_descriptions=tool_descriptions,
    )

    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    current_span = trace.get_current_span()
    current_span.add_event(
        "llm.request",
        {
            "purpose": "planner",
            "system_prompt_chars": len(PLANNER_SYSTEM_PROMPT),
            "user_prompt_preview": user_prompt[:2000],
        },
    )

    settings = get_settings()
    available_tools = set(registry.tool_names)
    response_messages: list[HumanMessage | SystemMessage] = list(messages)

    for repair_attempt in range(PLANNER_MAX_DECISION_REPAIRS + 1):
        start_time = time.perf_counter()
        status = "success" if repair_attempt == 0 else "repair_success"
        try:
            async with asyncio.timeout(settings.langgraph.planner_timeout_seconds):
                response = await llm.ainvoke(
                    response_messages,
                    max_tokens=settings.planner.max_tokens,
                    request_timeout=float(settings.langgraph.planner_timeout_seconds + 5),
                    response_format=PLANNER_RESPONSE_FORMAT,
                )
        except TimeoutError as exc:
            status = "timeout" if repair_attempt == 0 else "repair_timeout"
            ops_agent_llm_calls_total.labels(purpose="planner", status=status).inc()
            raise PlannerError(
                f"LLM planning timeout after {settings.langgraph.planner_timeout_seconds}s",
                investigation_id=state["investigation_id"],
            ) from exc
        except Exception as exc:
            status = "error" if repair_attempt == 0 else "repair_error"
            ops_agent_llm_calls_total.labels(purpose="planner", status=status).inc()
            raise PlannerError(
                f"LLM planning failed: {exc}",
                investigation_id=state["investigation_id"],
            ) from exc
        finally:
            elapsed = time.perf_counter() - start_time
            ops_agent_llm_latency_seconds.labels(purpose="planner").observe(elapsed)

        ops_agent_llm_calls_total.labels(purpose="planner", status=status).inc()

        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            metadata = response.usage_metadata
            model_name = getattr(llm, "model", "unknown")
            if "input_tokens" in metadata:
                input_tokens = metadata["input_tokens"]
                ops_agent_llm_tokens_total.labels(model=model_name, type="input").inc(input_tokens)
            if "output_tokens" in metadata:
                output_tokens = metadata["output_tokens"]
                ops_agent_llm_tokens_total.labels(model=model_name, type="output").inc(
                    output_tokens
                )

        response_content = str(response.content)
        current_span.add_event(
            "llm.response",
            {
                "purpose": "planner" if repair_attempt == 0 else "planner_repair",
                "attempt": repair_attempt + 1,
                "content_preview": response_content[:2000],
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        )

        try:
            parsed = _parse_planner_payload(response.content)
            tool = str(parsed.get("tool", "")).strip()
            reason = str(parsed.get("reason", ""))
            confidence_raw = parsed.get("confidence", 0.5)
            confidence = max(0.0, min(1.0, float(confidence_raw)))
            if not tool:
                raise ValueError("LLM returned empty tool name")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            parse_status = "parse_error" if repair_attempt == 0 else "repair_parse_error"
            ops_agent_llm_calls_total.labels(purpose="planner", status=parse_status).inc()
            raise PlannerError(
                f"LLM planning failed: failed to parse LLM response: {response_content[:200]}",
                investigation_id=state["investigation_id"],
            ) from exc

        rule_violation = _validate_planner_decision(state, tool, available_tools)
        if not rule_violation:
            return tool, reason, confidence, user_prompt, response_content

        ops_agent_llm_calls_total.labels(purpose="planner", status="invalid_decision").inc()
        current_span.add_event(
            "llm.response_invalid_decision",
            {
                "attempt": repair_attempt + 1,
                "tool": tool,
                "violation": rule_violation[:240],
            },
        )
        logger.warning(
            "Planner LLM decision violated sequencing constraints",
            investigation_id=state["investigation_id"],
            selected_tool=tool,
            violation=rule_violation,
            attempt=repair_attempt + 1,
            max_attempts=PLANNER_MAX_DECISION_REPAIRS + 1,
        )

        if repair_attempt >= PLANNER_MAX_DECISION_REPAIRS:
            raise PlannerError(
                f"LLM planning failed: invalid decision '{tool}' ({rule_violation})",
                investigation_id=state["investigation_id"],
                tool_name=tool,
            )

        response_messages = [
            *messages,
            HumanMessage(
                content=_build_planner_repair_instruction(
                    violation=rule_violation,
                    invalid_tool=tool,
                    response_preview=response_content,
                    completed_steps=state.get("completed_steps", []),
                )
            ),
        ]
        ops_agent_llm_calls_total.labels(purpose="planner", status="repair_requested").inc()

    raise PlannerError(
        "LLM planning failed: repair loop exhausted",
        investigation_id=state["investigation_id"],
    )


def _validate_planner_decision(
    state: InvestigationState,
    tool_name: str,
    available_tools: set[str],
) -> str | None:
    """Validate sequencing constraints for LLM planner choices."""
    completed = set(state.get("completed_steps", []))

    if tool_name in completed:
        return f"tool '{tool_name}' already completed"

    def _missing(required: str) -> bool:
        return required in available_tools and required not in completed

    if tool_name == "reasoning_tool":
        missing_analysis = [
            required
            for required in ("pattern_tool", "similarity_tool", "link_analysis_tool")
            if _missing(required)
        ]
        if missing_analysis:
            return f"reasoning_tool selected before analysis tools: {', '.join(missing_analysis)}"

    if tool_name == "recommendation_tool" and _missing("reasoning_tool"):
        return "recommendation_tool selected before reasoning_tool"

    if tool_name == "COMPLETE":
        if _missing("reasoning_tool"):
            return "COMPLETE selected before reasoning_tool"
        if _missing("recommendation_tool"):
            return "COMPLETE selected before recommendation_tool"

    return None


def _build_planner_repair_instruction(
    *,
    violation: str,
    invalid_tool: str,
    response_preview: str,
    completed_steps: list[str],
) -> str:
    completed = ", ".join(completed_steps) if completed_steps else "none"
    preview = response_preview.strip().replace("\x00", "")
    if len(preview) > 1200:
        preview = preview[:1200] + "..."
    return (
        "Your previous planner decision violated hard sequencing constraints.\n"
        f"Violation: {violation}\n"
        f"Invalid tool: {invalid_tool}\n"
        f"Completed steps: {completed}\n"
        "Return only one raw JSON object with keys: tool, reason, confidence.\n"
        "Do not use markdown or code fences.\n"
        "Choose a valid next tool based on the completed steps.\n\n"
        f"Previous response:\n{preview}"
    )


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```JSON").removeprefix("```")
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def _extract_balanced_json(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _parse_planner_payload(raw_content: Any) -> dict[str, Any]:
    if isinstance(raw_content, dict):
        return raw_content

    text = str(raw_content).strip()
    candidates: list[str] = []
    for candidate in (text, _strip_markdown_fences(text), _extract_balanced_json(text)):
        if isinstance(candidate, str):
            value = candidate.strip()
            if value and value not in candidates:
                candidates.append(value)

    for candidate in candidates:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Planner response is not a JSON object")


_TOOL_SEQUENCE = [
    "context_tool",
    "pattern_tool",
    "similarity_tool",
    "link_analysis_tool",
    "reasoning_tool",
    "recommendation_tool",
]


def _should_attempt_rule_draft(state: InvestigationState) -> bool:
    """Return True when fallback flow should attempt rule draft generation."""
    severity = str(state.get("severity", "")).upper()
    if severity in {"HIGH", "CRITICAL"}:
        return True

    recommendations = state.get("recommendations", [])
    if not isinstance(recommendations, list):
        return False

    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        rec_type = str(rec.get("type", "")).lower()
        if "rule" in rec_type:
            return True
    return False


def _rule_sequence_next_tool(
    state: InvestigationState,
    registry: ToolRegistry,
) -> tuple[str, str, float]:
    """Return the next tool in the canonical sequence, skipping already-completed ones.

    Used as a fallback when the LLM planner fails so investigations always complete.
    """
    completed = set(state["completed_steps"])
    available = set(registry.tool_names) if registry else set()

    for tool in _TOOL_SEQUENCE:
        if tool not in completed and tool in available:
            return tool, "rule-sequence fallback: LLM planner unavailable", 0.5

    if (
        "rule_draft_tool" in available
        and "rule_draft_tool" not in completed
        and _should_attempt_rule_draft(state)
    ):
        return "rule_draft_tool", "rule-sequence fallback: rule draft required", 0.6

    # All sequence tools done; complete.
    return "COMPLETE", "rule-sequence fallback: all tools completed", 1.0


def _build_findings_summary(state: InvestigationState) -> str:
    """Build a brief summary of findings so far for planner context."""
    parts: list[str] = []
    pattern = state.get("pattern_results", {})
    if pattern:
        score_count = len(pattern.get("scores", []))
        overall = pattern.get("overall_confidence", 0.0)
        parts.append(f"pattern({score_count} scores, confidence={overall})")
    similarity = state.get("similarity_results", {})
    if similarity:
        match_count = len(similarity.get("matches", []))
        parts.append(f"similarity({match_count} matches)")
    link_analysis = state.get("link_analysis_results", {})
    if link_analysis:
        signal_count = len(link_analysis.get("signals", []))
        parts.append(f"link_analysis({signal_count} signals)")
    if state.get("reasoning"):
        parts.append("reasoning(done)")
    rec_count = len(state.get("recommendations", []))
    if rec_count:
        parts.append(f"recommendations({rec_count})")
    return "; ".join(parts) if parts else "none"


def _planner_llm_circuit_open(state: InvestigationState) -> bool:
    """Open planner fallback circuit after first hard LLM planner failure."""
    for decision in state.get("planner_decisions", []):
        if not isinstance(decision, dict):
            continue
        reason = str(decision.get("reason") or "").lower()
        if "rule-sequence fallback: llm planner unavailable" in reason:
            return True
        if "rule-sequence fallback: planner circuit open" in reason:
            return True
    return False
