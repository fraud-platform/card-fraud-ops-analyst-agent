"""Unit tests for prompt templates and registry."""

from app.llm.prompts.investigation_v1 import get_investigation_template
from app.llm.prompts.templates import PromptRegistry, PromptTemplate, render_template


def test_prompt_registry_register_and_get():
    registry = PromptRegistry()
    template = PromptTemplate(
        name="foo",
        version="1",
        system_prompt="sys",
        user_template="hello {name}",
    )
    registry.register(template)

    got = registry.get("foo", "1")
    assert got is not None
    assert got.name == "foo"
    assert registry.list_versions("foo") == ["1"]


def test_render_investigation_template():
    template = get_investigation_template()
    messages, token_count = render_template(
        template,
        {
            "transaction_id": "txn-1",
            "card_id": "card-1",
            "amount": 42,
            "timestamp": "2026-01-01T00:00:00Z",
            "merchant_category": "grocery",
            "pattern_analysis": "none",
            "similarity_analysis": "none",
            "insight_summary": "summary",
        },
    )

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "txn-1" in messages[1]["content"]
    assert token_count > 0
