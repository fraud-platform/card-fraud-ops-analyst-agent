"""Self-contained HTML trace viewer for investigations."""

from __future__ import annotations

import html
import json
from typing import Any


def render_trace_html(data: dict[str, Any]) -> str:
    investigation_id = data.get("investigation_id", "unknown")
    status = data.get("status", "UNKNOWN")
    severity = data.get("severity", "LOW")
    confidence = data.get("confidence_score", 0.0)
    step_count = data.get("step_count", 0)
    max_steps = data.get("max_steps", 20)
    total_duration_ms = data.get("total_duration_ms")

    planner_decisions = data.get("planner_decisions", [])
    tool_executions = data.get("tool_executions", [])
    evidence = data.get("evidence", [])
    recommendations = data.get("recommendations", [])
    rule_draft = data.get("rule_draft")
    reasoning = data.get("reasoning", {})

    severity_colors = {
        "LOW": "#10b981",
        "MEDIUM": "#f59e0b",
        "HIGH": "#ef4444",
        "CRITICAL": "#dc2626",
    }
    severity_color = severity_colors.get(severity, "#6b7280")

    status_colors = {
        "COMPLETED": "#10b981",
        "IN_PROGRESS": "#3b82f6",
        "FAILED": "#ef4444",
        "TIMED_OUT": "#f59e0b",
        "PENDING": "#6b7280",
    }
    status_color = status_colors.get(status, "#6b7280")

    steps_html = _render_steps(planner_decisions, tool_executions, reasoning)
    results_html = _render_results(evidence, recommendations, rule_draft, reasoning)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Investigation Trace: {html.escape(investigation_id[:8])}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
        .header {{ background: #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid #334155; }}
        .header h1 {{ font-size: 18px; font-weight: 600; color: #94a3b8; margin-bottom: 8px; }}
        .header .id {{ font-size: 14px; font-family: 'Monaco', 'Menlo', monospace; color: #60a5fa; margin-bottom: 16px; }}
        .meta {{ display: flex; gap: 24px; flex-wrap: wrap; }}
        .meta-item {{ display: flex; flex-direction: column; gap: 4px; }}
        .meta-label {{ font-size: 11px; text-transform: uppercase; color: #64748b; }}
        .meta-value {{ font-size: 14px; font-weight: 500; }}
        .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; }}
        .section {{ background: #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid #334155; }}
        .section-title {{ font-size: 14px; font-weight: 600; color: #94a3b8; margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.05em; }}
        .step {{ border: 1px solid #334155; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }}
        .step-header {{ background: #334155; padding: 12px 16px; cursor: pointer; display: flex; align-items: center; gap: 12px; }}
        .step-header:hover {{ background: #475569; }}
        .step-number {{ background: #3b82f6; color: white; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; }}
        .step-title {{ flex: 1; font-size: 14px; }}
        .step-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; background: #475569; }}
        .step-badge.llm {{ background: #7c3aed; }}
        .step-content {{ padding: 16px; background: #0f172a; display: none; }}
        .step.open .step-content {{ display: block; }}
        .detail-block {{ background: #1e293b; border-radius: 6px; padding: 12px; margin-bottom: 12px; }}
        .detail-title {{ font-size: 12px; font-weight: 600; color: #60a5fa; margin-bottom: 8px; cursor: pointer; }}
        .detail-title:hover {{ text-decoration: underline; }}
        .detail-content {{ font-family: 'Monaco', 'Menlo', monospace; font-size: 12px; white-space: pre-wrap; word-break: break-all; color: #94a3b8; max-height: 200px; overflow-y: auto; display: none; }}
        .detail-content.open {{ display: block; }}
        .reason {{ color: #94a3b8; font-size: 13px; margin-top: 8px; }}
        .empty {{ color: #64748b; font-size: 14px; text-align: center; padding: 24px; }}
        .arrow {{ transition: transform 0.2s; }}
        .step.open .arrow {{ transform: rotate(90deg); }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Investigation</h1>
            <div class="id">{html.escape(investigation_id)}</div>
            <div class="meta">
                <div class="meta-item">
                    <span class="meta-label">Status</span>
                    <span class="badge" style="background: {status_color}20; color: {status_color};">{html.escape(status)}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Severity</span>
                    <span class="badge" style="background: {severity_color}20; color: {severity_color};">{html.escape(severity)}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Confidence</span>
                    <span class="meta-value">{confidence:.2f}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Steps</span>
                    <span class="meta-value">{step_count} / {max_steps}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Duration</span>
                    <span class="meta-value">{_format_duration(total_duration_ms)}</span>
                </div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Investigation Steps</div>
            {steps_html}
        </div>

        {results_html}
    </div>

    <script>
        document.querySelectorAll('.step-header').forEach(header => {{
            header.addEventListener('click', () => {{
                header.parentElement.classList.toggle('open');
            }});
        }});
        document.querySelectorAll('.detail-title').forEach(title => {{
            title.addEventListener('click', (e) => {{
                e.stopPropagation();
                title.nextElementSibling.classList.toggle('open');
            }});
        }});
    </script>
</body>
</html>"""


def _render_steps(
    planner_decisions: list[dict[str, Any]],
    tool_executions: list[dict[str, Any]],
    reasoning: dict[str, Any],
) -> str:
    if not planner_decisions and not tool_executions:
        return '<div class="empty">No steps recorded</div>'

    steps_html = []
    for i, decision in enumerate(planner_decisions):
        step_num = decision.get("step", i + 1)
        tool_name = decision.get("selected_tool", "unknown")
        reason = decision.get("reason", "")
        confidence = decision.get("confidence", 0.0)
        llm_prompt = decision.get("llm_prompt_preview")
        llm_response = decision.get("llm_response_preview")

        tool_exec = None
        if i < len(tool_executions):
            tool_exec = tool_executions[i]

        is_llm = bool(llm_prompt or llm_response) or tool_name == "reasoning_tool"

        tool_status = ""
        tool_time = ""
        if tool_exec:
            tool_status = tool_exec.get("status", "SUCCESS")
            tool_time = f"{tool_exec.get('execution_time_ms', 0)}ms"
            if tool_status == "SUCCESS":
                tool_status = '<span style="color: #10b981;">✓</span>'
            else:
                tool_status = '<span style="color: #ef4444;">✗</span>'

        llm_section = ""
        if llm_prompt or llm_response:
            llm_section = _render_llm_section(llm_prompt, llm_response)

        tool_io = ""
        if tool_exec:
            input_summary = tool_exec.get("input_summary", {})
            output_summary = tool_exec.get("output_summary", {})
            tool_io = f"""
                <div class="detail-block">
                    <div class="detail-title">▸ Input</div>
                    <div class="detail-content">{html.escape(json.dumps(input_summary, indent=2, default=str))}</div>
                </div>
                <div class="detail-block">
                    <div class="detail-title">▸ Output</div>
                    <div class="detail-content">{html.escape(json.dumps(output_summary, indent=2, default=str)[:2000])}</div>
                </div>
            """

        reasoning_section = ""
        if tool_name == "reasoning_tool" and reasoning:
            reasoning_section = _render_reasoning_section(reasoning)

        steps_html.append(f"""
            <div class="step">
                <div class="step-header">
                    <span class="arrow">▶</span>
                    <span class="step-number">{step_num}</span>
                    <span class="step-title">planner → {html.escape(tool_name)} ({confidence:.2f})</span>
                    {'<span class="step-badge llm">LLM</span>' if is_llm else ""}
                    {f'<span class="step-badge">{tool_time}</span>' if tool_time else ""}
                    {f'<span class="step-badge">{tool_status}</span>' if tool_status else ""}
                </div>
                <div class="step-content">
                    <div class="reason">{html.escape(reason)}</div>
                    {llm_section}
                    {tool_io}
                    {reasoning_section}
                </div>
            </div>
        """)

    return "".join(steps_html)


def _render_llm_section(prompt: str | None, response: str | None) -> str:
    sections = []
    if prompt:
        sections.append(f"""
            <div class="detail-block">
                <div class="detail-title">▸ LLM Prompt</div>
                <div class="detail-content">{html.escape(prompt[:2000])}</div>
            </div>
        """)
    if response:
        sections.append(f"""
            <div class="detail-block">
                <div class="detail-title">▸ LLM Response</div>
                <div class="detail-content">{html.escape(response[:2000])}</div>
            </div>
        """)
    return "".join(sections)


def _render_reasoning_section(reasoning: dict[str, Any]) -> str:
    narrative = reasoning.get("narrative", "")
    risk_level = reasoning.get("risk_level", reasoning.get("severity", "UNKNOWN"))
    confidence = reasoning.get("confidence", 0.0)
    key_findings = reasoning.get("key_findings", [])
    llm_prompt = reasoning.get("llm_prompt_preview")
    llm_response = reasoning.get("llm_response_preview")

    findings_html = ""
    if key_findings:
        findings_items = "".join(f"<li>{html.escape(str(f))}</li>" for f in key_findings[:5])
        findings_html = f"<ul style='margin: 8px 0 8px 20px; color: #94a3b8;'>{findings_items}</ul>"

    llm_section = _render_llm_section(llm_prompt, llm_response)

    return f"""
        <div class="detail-block" style="margin-top: 12px;">
            <div style="display: flex; gap: 16px; margin-bottom: 8px;">
                <span><strong>Risk:</strong> <span style="color: #f59e0b;">{html.escape(risk_level)}</span></span>
                <span><strong>Confidence:</strong> {confidence:.2f}</span>
            </div>
            <div style="color: #e2e8f0; margin-bottom: 8px;">{html.escape(narrative)}</div>
            {findings_html}
            {llm_section}
        </div>
    """


def _render_results(
    evidence: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    rule_draft: dict[str, Any] | None,
    reasoning: dict[str, Any],
) -> str:
    sections = []

    if evidence:
        evidence_items = ""
        for ev in evidence[:10]:
            kind = ev.get("kind") or ev.get("category") or ev.get("tool") or "unknown"
            desc = ev.get("description") or json.dumps(ev.get("payload", {}), default=str)[:100]
            evidence_items += (
                f"<li><strong>{html.escape(str(kind))}:</strong> {html.escape(desc)}</li>"
            )
        sections.append(f"""
            <div class="section">
                <div class="section-title">Evidence ({len(evidence)} items)</div>
                <ul style="margin-left: 20px; color: #94a3b8;">{evidence_items}</ul>
            </div>
        """)

    if recommendations:
        rec_items = ""
        for rec in recommendations[:10]:
            rec_type = rec.get("type", "REVIEW")
            title = rec.get("title", "Recommendation")
            rec_items += f"<li><strong>[{html.escape(rec_type)}]</strong> {html.escape(title)}</li>"
        sections.append(f"""
            <div class="section">
                <div class="section-title">Recommendations ({len(recommendations)} items)</div>
                <ul style="margin-left: 20px; color: #94a3b8;">{rec_items}</ul>
            </div>
        """)

    if rule_draft:
        rule_name = rule_draft.get("rule_name", "Draft Rule")
        rule_desc = rule_draft.get("rule_description", "")
        conditions = rule_draft.get("conditions", [])
        conditions_json = json.dumps(conditions, indent=2, default=str)
        sections.append(f"""
            <div class="section">
                <div class="section-title">Rule Draft</div>
                <div style="margin-bottom: 8px;"><strong>{html.escape(rule_name)}</strong></div>
                <div style="color: #94a3b8; margin-bottom: 12px;">{html.escape(rule_desc)}</div>
                <div class="detail-block">
                    <div class="detail-title">▸ Conditions</div>
                    <div class="detail-content">{html.escape(conditions_json[:1000])}</div>
                </div>
            </div>
        """)

    return "".join(sections)


def _format_duration(ms: int | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"
