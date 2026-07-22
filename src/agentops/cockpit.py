"""AgentOps Cockpit web UI (FastAPI + HTMX + Tailwind + Chart.js).

Run:  uvicorn agentops.cockpit:app --port 8100
Shows fleet metrics, cost breakdown, and the live triage feed. A deep-link jumps
to the SigNoz UI for the full trace waterfall.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from jinja2 import Template

from .telemetry_store import SigNozClient, compute_analytics, load_traces
from .triage import fleet_alerts, triage_all

app = FastAPI(title="AgentOps Cockpit")
SIGNOZ_URL = os.environ.get("SIGNOZ_URL", "http://localhost:8080")

_PAGE = Template(
    """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentOps Cockpit</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://unpkg.com/htmx.org@2.0.3"></script>
</head>
<body class="bg-slate-950 text-slate-100 font-sans">
<div class="max-w-6xl mx-auto p-6">
  <header class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-2xl font-bold">AgentOps Cockpit</h1>
      <p class="text-slate-400 text-sm">Observability + auto-triage for AI agents, powered by SigNoz</p>
    </div>
    <div class="text-right text-sm">
      <span class="px-2 py-1 rounded {{ 'bg-emerald-700' if signoz_up else 'bg-rose-700' }}">
        SigNoz {{ 'connected' if signoz_up else 'offline (ledger mode)' }}
      </span>
      <div class="mt-2"><a class="text-sky-400 underline" href="{{ signoz_url }}" target="_blank">Open SigNoz UI &rarr;</a></div>
    </div>
  </header>

  <section class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
    {% for label, value in kpis %}
    <div class="bg-slate-900 rounded-xl p-4 border border-slate-800">
      <div class="text-slate-400 text-xs uppercase tracking-wide">{{ label }}</div>
      <div class="text-2xl font-bold mt-1">{{ value }}</div>
    </div>
    {% endfor %}
  </section>

  <section class="grid md:grid-cols-2 gap-4 mb-6">
    <div class="bg-slate-900 rounded-xl p-4 border border-slate-800">
      <h2 class="font-semibold mb-2">Cost by model (USD)</h2>
      <div class="relative h-64"><canvas id="modelChart"></canvas></div>
    </div>
    <div class="bg-slate-900 rounded-xl p-4 border border-slate-800">
      <h2 class="font-semibold mb-2">Cost by user (USD)</h2>
      <div class="relative h-64"><canvas id="userChart"></canvas></div>
    </div>
  </section>

  {% if alerts %}
  <section class="bg-rose-950 border border-rose-800 rounded-xl p-4 mb-6">
    <h2 class="font-semibold mb-2 text-rose-300">Fleet alerts</h2>
    <ul class="list-disc pl-6 text-rose-200 text-sm">
      {% for a in alerts %}<li>{{ a }}</li>{% endfor %}
    </ul>
  </section>
  {% endif %}

  <section class="bg-slate-900 rounded-xl p-4 border border-slate-800">
    <h2 class="font-semibold mb-3">Triage Copilot ({{ reports|length }} incidents)</h2>
    {% if not reports %}<p class="text-emerald-400 text-sm">No incidents. Fleet healthy.</p>{% endif %}
    <div class="space-y-3">
    {% for r in reports %}
      <div class="border border-slate-800 rounded-lg p-3">
        <div class="flex items-center gap-2">
          <span class="text-xs px-2 py-0.5 rounded
            {{ {'CRITICAL':'bg-rose-700','HIGH':'bg-orange-700','MEDIUM':'bg-amber-700'}.get(r.severity,'bg-slate-700') }}">
            {{ r.severity }}</span>
          <span class="font-medium">{{ r.title }}</span>
          <a class="ml-auto text-sky-400 text-xs underline"
             href="{{ signoz_url }}/trace/{{ r.trace_id }}" target="_blank">trace &rarr;</a>
        </div>
        <p class="text-sm mt-2"><span class="text-slate-400">Root cause:</span> {{ r.root_cause }}</p>
        <p class="text-sm mt-1"><span class="text-slate-400">Suggested fix:</span> {{ r.suggested_fix }}</p>
      </div>
    {% endfor %}
    </div>
  </section>
</div>
<script>
  const mk = (id, data) => new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels: Object.keys(data), datasets: [{ data: Object.values(data),
      backgroundColor: '#38bdf8' }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: '#cbd5e1' } }, y: { ticks: { color: '#cbd5e1' } } } }
  });
  mk('modelChart', {{ cost_by_model | tojson }});
  mk('userChart', {{ cost_by_user | tojson }});
</script>
</body></html>"""
)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    traces = load_traces()
    a = compute_analytics(traces)
    reports = triage_all(traces)
    kpis = [
        ("Runs", a.total_traces),
        ("Error rate", f"{a.error_rate:.0%}"),
        ("Total spend", f"${a.total_cost_usd:.4f}"),
        ("p95 latency", f"{a.p95_latency_ms:.0f}ms"),
    ]
    return _PAGE.render(
        signoz_up=SigNozClient().is_up(),
        signoz_url=SIGNOZ_URL,
        kpis=kpis,
        cost_by_model=a.cost_by_model or {"(none)": 0},
        cost_by_user=a.cost_by_user or {"(none)": 0},
        alerts=fleet_alerts(a),
        reports=reports,
    )


@app.get("/api/analytics")
def api_analytics() -> dict:
    a = compute_analytics(load_traces())
    return a.__dict__
