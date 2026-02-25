"""Rule draft tool - generates fraud detection rule drafts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.agent.state import update_state
from app.tools._core.rule_draft_logic import assemble_draft_payload
from app.tools.base import BaseTool

if TYPE_CHECKING:
    from app.agent.state import InvestigationState

logger = structlog.get_logger(__name__)


class RuleDraftTool(BaseTool):
    """Generate a fraud detection rule draft based on recommendations and investigation evidence."""

    @property
    def name(self) -> str:
        return "rule_draft_tool"

    @property
    def description(self) -> str:
        return "Generate a fraud detection rule draft based on recommendations and investigation evidence"

    async def execute(self, state: InvestigationState) -> InvestigationState:
        recommendations = state["recommendations"]
        reasoning = state["reasoning"]

        if not recommendations:
            return {**state, "rule_draft": None}

        evidence = [
            {
                "evidence_kind": ev.get("category", "unknown"),
                "evidence_payload": ev.get("data", {}),
            }
            for ev in state.get("evidence", [])
        ]

        insight = {
            "summary": reasoning.get("narrative", ""),
            "severity": state["severity"],
        }

        primary_recommendation = recommendations[0]

        try:
            draft_payload = assemble_draft_payload(
                recommendation=primary_recommendation,
                insight=insight,
                evidence=evidence,
            )

            rule_draft = {
                "rule_name": draft_payload.rule_name,
                "rule_description": draft_payload.rule_description,
                "conditions": [
                    {
                        "field_name": c.field_name,
                        "operator": c.operator,
                        "value": c.value,
                        "logical_op": c.logical_op,
                    }
                    for c in draft_payload.conditions
                ],
                "thresholds": dict(draft_payload.thresholds),
                "metadata": dict(draft_payload.metadata),
            }
        except Exception:
            logger.error(
                "Rule draft generation failed",
                investigation_id=state["investigation_id"],
                exc_info=True,
            )
            rule_draft = None

        return update_state(state, rule_draft=rule_draft)
