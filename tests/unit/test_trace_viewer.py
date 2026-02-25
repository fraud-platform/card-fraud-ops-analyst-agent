"""Unit tests for investigation trace viewer HTML rendering."""

from app.templates.trace_viewer import render_trace_html


def test_trace_viewer_renders_tool_input_output() -> None:
    html = render_trace_html(
        {
            "investigation_id": "inv-123",
            "status": "COMPLETED",
            "severity": "HIGH",
            "confidence_score": 0.82,
            "step_count": 2,
            "max_steps": 20,
            "planner_decisions": [
                {
                    "step": 1,
                    "selected_tool": "pattern_tool",
                    "reason": "Analyze velocity signals",
                    "confidence": 0.9,
                }
            ],
            "tool_executions": [
                {
                    "tool_name": "pattern_tool",
                    "status": "SUCCESS",
                    "execution_time_ms": 12,
                    "input_summary": {"transaction_id": "txn-1"},
                    "output_summary": {"patterns_detected": ["velocity"]},
                }
            ],
            "reasoning": {"risk_level": "HIGH", "confidence": 0.82, "narrative": "summary"},
            "evidence": [],
            "recommendations": [],
            "rule_draft": None,
        }
    )

    assert "pattern_tool" in html
    assert "transaction_id" in html
    assert "patterns_detected" in html
