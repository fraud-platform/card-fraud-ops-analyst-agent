"""Evidence builder - Create structured evidence envelopes.

This module contains ZERO database access. Pure functions for building evidence.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.agents.freshness import compute_freshness_weight


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Standardized evidence storage format."""

    evidence_id: str
    evidence_kind: str
    investigation_id: str
    category: str
    strength: float
    description: str
    supporting_data: dict[str, Any]
    timestamp: datetime
    freshness_weight: float
    related_transaction_ids: list[str]
    evidence_references: dict[str, Any]

    def to_jsonb(self) -> dict[str, Any]:
        """Convert to JSONB-compatible dict for storage."""
        return {
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind,
            "category": self.category,
            "strength": self.strength,
            "description": self.description,
            "supporting_data": self.supporting_data,
            "timestamp": self.timestamp.isoformat(),
            "freshness_weight": self.freshness_weight,
            "related_transaction_ids": self.related_transaction_ids,
            "evidence_references": self.evidence_references,
        }


class EvidenceBuilder:
    """Build structured evidence envelopes."""

    def build_pattern_evidence(
        self,
        investigation_id: str,
        pattern_name: str,
        score: float,
        description: str,
        supporting_data: dict[str, Any],
        transaction_timestamp: datetime | None = None,
    ) -> EvidenceEnvelope:
        """Build pattern evidence envelope."""
        evidence_id = str(uuid4())
        related_txns = supporting_data.get("related_transaction_ids", [])

        return EvidenceEnvelope(
            evidence_id=evidence_id,
            evidence_kind="pattern",
            investigation_id=investigation_id,
            category=pattern_name,
            strength=score,
            description=description,
            supporting_data=supporting_data,
            timestamp=datetime.now(UTC),
            freshness_weight=compute_freshness_weight(
                "pattern_velocity", transaction_timestamp or datetime.now(UTC)
            ),
            related_transaction_ids=related_txns,
            evidence_references={},
        )

    def build_similarity_evidence(
        self,
        investigation_id: str,
        match: dict[str, Any],
    ) -> EvidenceEnvelope:
        """Build similarity evidence envelope."""
        evidence_id = str(uuid4())
        match_type = match.get("match_type", "unknown")
        match_id = match.get("match_id", "")
        details = match.get("details", {})
        timestamp = details.get("transaction_timestamp")

        return EvidenceEnvelope(
            evidence_id=evidence_id,
            evidence_kind="similarity",
            investigation_id=investigation_id,
            category=match_type,
            strength=match.get("similarity_score", 0.0),
            description=f"Similar transaction ({match_type}): {match_id}",
            supporting_data=match,
            timestamp=datetime.now(UTC),
            freshness_weight=compute_freshness_weight(
                f"similarity_{match_type}",
                timestamp or datetime.now(UTC),
            ),
            related_transaction_ids=[match_id],
            evidence_references={"counter_evidence": match.get("counter_evidence") or []},
        )

    def build_counter_evidence(
        self,
        investigation_id: str,
        evidence_type: str,
        strength: float,
        description: str,
        supporting_data: dict[str, Any],
    ) -> EvidenceEnvelope:
        """Build counter-evidence envelope."""
        evidence_id = str(uuid4())
        related_txns = supporting_data.get("transaction_ids", [])

        return EvidenceEnvelope(
            evidence_id=evidence_id,
            evidence_kind="counter_evidence",
            investigation_id=investigation_id,
            category=evidence_type,
            strength=strength,
            description=description,
            supporting_data=supporting_data,
            timestamp=datetime.now(UTC),
            freshness_weight=compute_freshness_weight(
                f"counter_evidence_{evidence_type}",
                datetime.now(UTC),
            ),
            related_transaction_ids=related_txns,
            evidence_references={},
        )

    def build_conflict_evidence(
        self,
        investigation_id: str,
        conflict_matrix: dict[str, Any],
    ) -> EvidenceEnvelope:
        """Build conflict matrix evidence envelope."""
        evidence_id = str(uuid4())
        strategy = conflict_matrix.get("resolution_strategy", "unknown")
        score = conflict_matrix.get("overall_conflict_score", 0.0)

        return EvidenceEnvelope(
            evidence_id=evidence_id,
            evidence_kind="conflict",
            investigation_id=investigation_id,
            category="resolution",
            strength=score,
            description=f"Conflict analysis: {strategy}",
            supporting_data=conflict_matrix,
            timestamp=datetime.now(UTC),
            freshness_weight=1.0,
            related_transaction_ids=[],
            evidence_references={},
        )

    def build_llm_reasoning_evidence(
        self,
        investigation_id: str,
        llm_reasoning: dict[str, Any],
    ) -> EvidenceEnvelope:
        """Build LLM reasoning evidence envelope."""
        evidence_id = str(uuid4())

        return EvidenceEnvelope(
            evidence_id=evidence_id,
            evidence_kind="llm_reasoning",
            investigation_id=investigation_id,
            category="reasoning",
            strength=llm_reasoning.get("confidence", 0.5),
            description=llm_reasoning.get("narrative_summary", "LLM analysis"),
            supporting_data=llm_reasoning,
            timestamp=datetime.now(UTC),
            freshness_weight=1.0,
            related_transaction_ids=[],
            evidence_references={},
        )
