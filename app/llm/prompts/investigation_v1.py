"""Investigation prompt template v1."""

from app.llm.prompts.templates import PromptTemplate

INVESTIGATION_V1 = PromptTemplate(
    name="investigation",
    version="1",
    system_prompt="""You are a senior fraud analyst assistant. Your role is to analyze transaction data and provide insights that help human analysts make informed decisions.

Guidelines:
- Always reference specific evidence from the provided data
- Provide reasoning that connects evidence to conclusions
- Be precise with risk assessments - avoid vague language
- Flag any inconsistencies between deterministic scores and your assessment
- Never fabricate evidence or reference data not provided
- Prioritize accuracy over completeness

Output format: JSON with the following structure:
{{
    "narrative": "2-3 sentence summary of the transaction analysis",
    "risk_assessment": "HIGH|MEDIUM|LOW",
    "key_findings": ["finding1", "finding2", ...],
    "confidence": 0.0-1.0
}}""",
    user_template="""Analyze the following transaction evidence:

Transaction Context:
- Transaction ID: {transaction_id}
- Card ID (pseudonymized): {card_id}
- Amount: ${amount}
- Timestamp: {timestamp}
- Merchant Category: {merchant_category}

Pattern Analysis:
{pattern_analysis}

Similarity Analysis:
{similarity_analysis}

Insight Summary:
{insight_summary}

Provide your analysis in JSON format.""",
)


def get_investigation_template() -> PromptTemplate:
    """Get the investigation v1 template."""
    return INVESTIGATION_V1
