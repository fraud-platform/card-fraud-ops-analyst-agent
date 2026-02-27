"""Shared HTML reporter for E2E tests.

Produces a request-left / response-right side-by-side HTML report with
JSON syntax highlighting — same visual format as the standalone e2e_local_test.py.

Used by both test_scenarios.py (via pytest fixture) and scripts/e2e_local_test.py.
"""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class HttpStage:
    """One recorded HTTP request/response stage."""

    name: str
    status: int  # 200 = pass, 0 = error, anything else = fail
    elapsed_ms: float
    request_method: str
    request_url: str
    request_body: dict | None = None
    response_status: int | None = None
    response_body: dict | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)  # validation notes


@dataclass
class ScenarioResult:
    """All stages for one named scenario."""

    name: str
    stages: list[HttpStage] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(s.status == 200 for s in self.stages if s.status != 0) and not any(
            s.status == 0 for s in self.stages
        )

    @property
    def skipped(self) -> bool:
        return len(self.stages) == 0


class E2EReporter:
    """Collects stage data and generates a custom HTML report."""

    def __init__(self, title: str = "E2E Test Report", metadata: dict | None = None) -> None:
        self.title = title
        self.start_time = time.perf_counter()
        self._scenarios: list[ScenarioResult] = []
        self._current: ScenarioResult | None = None
        self._metadata = metadata or {}

    # ------------------------------------------------------------------
    # Recording API
    # ------------------------------------------------------------------

    def begin_scenario(self, name: str) -> None:
        """Start a new named scenario section."""
        self._current = ScenarioResult(name=name)
        self._scenarios.append(self._current)

    def record_stage(
        self,
        stage_name: str,
        status: int,
        elapsed_ms: float,
        request_method: str,
        request_url: str,
        request_body: dict | None = None,
        response_status: int | None = None,
        response_body: dict | None = None,
        error: str | None = None,
        notes: list[str] | None = None,
    ) -> None:
        """Record one HTTP stage into the current scenario."""
        if self._current is None:
            self.begin_scenario("Default")
        stage = HttpStage(
            name=stage_name,
            status=status,
            elapsed_ms=elapsed_ms,
            request_method=request_method,
            request_url=request_url,
            request_body=request_body,
            response_status=response_status,
            response_body=response_body,
            error=error,
            notes=notes or [],
        )
        self._current.stages.append(stage)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # HTML generation
    # ------------------------------------------------------------------

    def write_html(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render(), encoding="utf-8")

    def _render(self) -> str:
        total_ms = (time.perf_counter() - self.start_time) * 1000
        passed = sum(1 for s in self._scenarios if s.passed)
        skipped = sum(1 for s in self._scenarios if s.skipped)
        failed = len(self._scenarios) - passed - skipped
        kpi_section = self._render_kpi_section()

        pass_color = "#059669" if failed == 0 else "#dc2626"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(self.title)}</title>
  <style>
    *{{box-sizing:border-box;}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.6;margin:0;padding:20px;background:#f5f5f5;}}
    .container{{max-width:1500px;margin:0 auto;background:#fff;border-radius:8px;padding:30px;box-shadow:0 2px 10px rgba(0,0,0,.12);}}
    h1{{color:#1a1a1a;border-bottom:2px solid #e0e0e0;padding-bottom:10px;margin-bottom:20px;}}
    .meta{{color:#666;margin-bottom:20px;font-size:14px;}}
    .summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:15px;margin-bottom:30px;}}
    .kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:0 0 30px 0;}}
    .kpi-card{{background:#f8f9fa;border:1px solid #e1e4e8;border-radius:6px;padding:12px;}}
    .kpi-card.pass{{border-left:4px solid #059669;}} .kpi-card.fail{{border-left:4px solid #dc2626;}}
    .kpi-name{{font-size:12px;font-weight:700;color:#374151;margin-bottom:4px;text-transform:uppercase;letter-spacing:.3px;}}
    .kpi-value{{font-size:20px;font-weight:700;color:#111827;margin-bottom:4px;}}
    .kpi-target{{font-size:12px;color:#6b7280;}}
    .card{{background:#f8f9fa;border:1px solid #e1e4e8;border-radius:6px;padding:15px;}}
    .card h3{{margin:0 0 6px;color:#374151;font-size:12px;text-transform:uppercase;letter-spacing:.5px;}}
    .card .val{{font-size:28px;font-weight:700;}}
    .card.ok .val{{color:#059669;}} .card.fail .val{{color:#dc2626;}} .card.skip .val{{color:#9ca3af;}}
    .scenario{{margin-bottom:30px;border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;}}
    .scenario.pass{{border-left:4px solid #059669;}} .scenario.fail{{border-left:4px solid #dc2626;}} .scenario.skip{{border-left:4px solid #9ca3af;}}
    .sc-header{{background:#f8f9fa;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;font-weight:600;cursor:pointer;user-select:none;}}
    .sc-header:hover{{background:#f0f0f0;}}
    .sc-body{{padding:15px;display:none;}}
    .sc-body.open{{display:block;}}
    .stage{{margin-bottom:16px;border:1px solid #e5e7eb;border-radius:4px;overflow:hidden;}}
    .stage-hdr{{background:#f3f4f6;padding:8px 12px;display:flex;justify-content:space-between;font-size:13px;font-weight:600;cursor:pointer;user-select:none;}}
    .stage-hdr:hover{{background:#e5e7eb;}}
    .stage-body{{display:none;}}
    .stage-body.open{{display:block;}}
    .stage-toggle{{font-size:11px;margin-right:8px;color:#6b7280;}}
    .req-resp{{display:grid;grid-template-columns:1fr 1fr;gap:0;}}
    .pane{{border-top:1px solid #e5e7eb;overflow:hidden;}}
    .pane+.pane{{border-left:1px solid #e5e7eb;}}
    .pane-hdr{{background:#e8e8e8;padding:6px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#374151;}}
    .pane pre{{margin:0;padding:12px;font-size:11.5px;line-height:1.5;overflow-x:auto;background:#fafafa;}}
    .notes{{padding:8px 12px;font-size:12px;color:#374151;border-top:1px solid #e5e7eb;background:#fffbeb;}}
    .note.pass{{color:#059669;}} .note.fail{{color:#dc2626;}} .note.warn{{color:#d97706;}}
    .badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;margin-left:6px;}}
    .badge.get{{background:#d1fae5;color:#059669;}} .badge.post{{background:#dbeafe;color:#1d4ed8;}}
    .badge.ok{{background:#d1fae5;color:#059669;}} .badge.err{{background:#fee2e2;color:#dc2626;}}
    .jk{{color:#0d47a1;}} .js{{color:#032f62;}} .jn{{color:#1f6419;}} .jb{{color:#0d47a1;}} .jnull{{color:#999;}}
    footer{{margin-top:40px;padding-top:20px;border-top:1px solid #e5e7eb;color:#9ca3af;font-size:12px;}}
  </style>
</head>
<body>
<div class="container">
  <h1>E2E Test Report - {html.escape(self.title)}</h1>
  <p class="meta">
    Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} &nbsp;|&nbsp;
    Total duration: {total_ms:.0f}ms
    {self._render_metadata()}
  </p>

  <div class="summary">
    <div class="card {"ok" if failed == 0 else "fail"}">
      <h3>Total</h3><div class="val">{len(self._scenarios)}</div>
    </div>
    <div class="card ok"><h3>Passed</h3><div class="val" style="color:{pass_color}">{passed}</div></div>
    <div class="card fail"><h3>Failed</h3><div class="val">{failed}</div></div>
    <div class="card skip"><h3>Skipped</h3><div class="val">{skipped}</div></div>
  </div>

  {kpi_section}

  <div class="scenarios">
    {self._render_scenarios()}
  </div>

  <footer>Card Fraud Ops Analyst Agent &mdash; E2E Test Report</footer>
</div>
<script>
  document.querySelectorAll('.sc-header').forEach(h => {{
    h.addEventListener('click', () => {{
      const body = h.nextElementSibling;
      body.classList.toggle('open');
      h.querySelector('.toggle').textContent = body.classList.contains('open') ? '^' : 'v';
    }});
  }});
  document.querySelectorAll('.stage-hdr').forEach(h => {{
    h.addEventListener('click', (e) => {{
      e.stopPropagation();
      const body = h.nextElementSibling;
      body.classList.toggle('open');
      h.querySelector('.stage-toggle').textContent = body.classList.contains('open') ? '^' : 'v';
    }});
  }});
  // Auto-open failed/passed scenarios
  document.querySelectorAll('.sc-body').forEach(b => {{
    if (b.previousElementSibling.closest('.scenario').classList.contains('pass') ||
        b.previousElementSibling.closest('.scenario').classList.contains('fail')) {{
      b.classList.add('open');
      b.previousElementSibling.querySelector('.toggle').textContent = '^';
    }}
  }});
</script>
</body>
</html>"""

    def _extract_acceptance_kpis(self) -> dict[str, dict] | None:
        for scenario in reversed(self._scenarios):
            for stage in reversed(scenario.stages):
                if stage.name != "Evaluate Acceptance KPIs":
                    continue
                body = stage.response_body
                if not isinstance(body, dict):
                    continue
                kpis = body.get("kpis")
                if isinstance(kpis, dict):
                    return kpis
        return None

    def _render_kpi_section(self) -> str:
        kpis = self._extract_acceptance_kpis()
        if not kpis:
            return ""
        cards: list[str] = []
        for name, metric in kpis.items():
            status_cls = "pass" if bool(metric.get("pass")) else "fail"
            value = html.escape(str(metric.get("value", "n/a")))
            target = html.escape(str(metric.get("target", "n/a")))
            detail = html.escape(str(metric.get("description", "")))
            cards.append(
                f"""
    <div class="kpi-card {status_cls}">
      <div class="kpi-name">{html.escape(name)}</div>
      <div class="kpi-value">{value}</div>
      <div class="kpi-target">target: {target}</div>
      <div class="kpi-target">{detail}</div>
    </div>"""
            )
        return f"""
  <div class="kpi-grid">
    {"".join(cards)}
  </div>"""

    def _render_metadata(self) -> str:
        if not self._metadata:
            return ""
        parts = []
        for key, value in self._metadata.items():
            parts.append(f"&nbsp;|&nbsp; {key}: {html.escape(str(value))}")
        return "".join(parts)

    def _render_scenarios(self) -> str:
        parts = []
        for sc in self._scenarios:
            cls = "skip" if sc.skipped else ("pass" if sc.passed else "fail")
            label = "SKIP" if sc.skipped else ("PASS" if sc.passed else "FAIL")
            label_color = "#9ca3af" if sc.skipped else ("#059669" if sc.passed else "#dc2626")
            total_ms = sum(s.elapsed_ms for s in sc.stages)
            parts.append(f"""
    <div class="scenario {cls}">
      <div class="sc-header">
        <span>Scenario: <strong>{html.escape(sc.name)}</strong>
          &nbsp;|&nbsp; {len(sc.stages)} stage(s) &nbsp;|&nbsp; {total_ms:.0f}ms
        </span>
        <span>
          <span style="color:{label_color};font-weight:700;">{label}</span>
          &nbsp;<span class="toggle">v</span>
        </span>
      </div>
      <div class="sc-body">
        {self._render_stages(sc.stages)}
      </div>
    </div>""")
        return "\n".join(parts)

    def _render_stages(self, stages: list[HttpStage]) -> str:
        parts = []
        for i, s in enumerate(stages, 1):
            ok = s.status == 200
            hdr_color = "#059669" if ok else ("#dc2626" if s.status != 0 else "#9ca3af")
            method_cls = s.request_method.lower()

            req_html = f"""
        <div class="pane">
          <div class="pane-hdr">
            <span class="badge {method_cls}">{html.escape(s.request_method)}</span>
            &nbsp;<code style="font-size:11px">{html.escape(s.request_url)}</code>
          </div>
          <pre>{self._fmt_json(s.request_body) if s.request_body else "<em>no body</em>"}</pre>
        </div>"""

            if s.error:
                resp_html = f"""
        <div class="pane">
          <div class="pane-hdr">Error</div>
          <pre style="color:#dc2626">{html.escape(s.error)}</pre>
        </div>"""
            else:
                status_cls = "ok" if ok else "err"
                resp_html = f"""
        <div class="pane">
          <div class="pane-hdr">
            <span class="badge {status_cls}">HTTP {s.response_status}</span>
            &nbsp;{s.elapsed_ms:.0f}ms
          </div>
          <pre>{self._fmt_json(s.response_body) if s.response_body else "<em>empty</em>"}</pre>
        </div>"""

            notes_html = ""
            if s.notes:
                rows = "".join(
                    f'<div class="note {self._note_cls(n)}">{html.escape(n)}</div>' for n in s.notes
                )
                notes_html = f'<div class="notes">{rows}</div>'

            parts.append(f"""
      <div class="stage">
        <div class="stage-hdr">
          <span><span class="stage-toggle">v</span>Stage {i}: {html.escape(s.name)}</span>
          <span style="color:{hdr_color};">HTTP {s.status} ({s.elapsed_ms:.0f}ms)</span>
        </div>
        <div class="stage-body">
          <div class="req-resp">
            {req_html}
            {resp_html}
          </div>
          {notes_html}
        </div>
      </div>""")
        return "\n".join(parts)

    @staticmethod
    def _note_cls(note: str) -> str:
        nl = note.lower()
        if nl.startswith("[pass]") or nl.startswith("pass"):
            return "pass"
        if nl.startswith("[fail]") or nl.startswith("fail"):
            return "fail"
        if nl.startswith("[warn]") or nl.startswith("warn"):
            return "warn"
        return ""

    @staticmethod
    def _fmt_json(data: dict | list | None) -> str:
        if data is None:
            return "<em>null</em>"

        # Check if this is a large list (like transaction items) and truncate it
        if isinstance(data, list) and len(data) > 20:
            return f"<em>Large array ({len(data)} items) - truncated for readability</em>"

        json_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        # Also truncate if the JSON string itself is too long (>5000 chars)
        if len(json_str) > 5000:
            json_str = json_str[:5000]
            json_str += "\n... (truncated)"

        raw = html.escape(json_str)
        # Highlight keys
        raw = re.sub(r"&quot;([^&]+)&quot;:", r'<span class="jk">&quot;\1&quot;</span>:', raw)
        # Highlight string values
        raw = re.sub(
            r": &quot;([^&]*)&quot;",
            r': <span class="js">&quot;\1&quot;</span>',
            raw,
        )
        raw = raw.replace(": true", ': <span class="jb">true</span>')
        raw = raw.replace(": false", ': <span class="jb">false</span>')
        raw = raw.replace(": null", ': <span class="jnull">null</span>')
        return raw
