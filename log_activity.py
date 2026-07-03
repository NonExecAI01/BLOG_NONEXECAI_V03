#!/usr/bin/env python3
"""Unified activity, cost, and prompt log for non-exec.ai prompt cycling."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "NonExecAI Cost Cycling"
UNIFIED_LOG = LOG_DIR / "activity-cost-and-prompt-log.txt"
PROMPT_SOURCE = "automation/prompts/governance-authority-agent.md"
PROMPT_REPO = "aimodelpromptneai (Cursor prefills: automation/prefill/*.json)"
COSTS_JSON = ROOT / "automation" / "model-run-costs.json"

PROMPT_SUMMARY = """PROMPT IN USE (master)
--------------------
Name: non-exec.ai - Daily Governance Authority Agent
Source file: automation/prompts/governance-authority-agent.md
Purpose: Build non-exec.ai as the definitive source for AI corporate governance
         and canonical registry for AI agents/models in a board-governance context.

Schedule (current): 06:00 GMT = DAWN | 16:00 GMT = AFTERNOON
- DAWN: intelligence scan, gap analysis, dawn reports (no public publish unless critical fixes)
- AFTERNOON: authoritative content + registry updates + authority signals (audit/briefing/llms.txt)

Each run binds: model slug, phase codename, UTC hour via automation prefill JSON.
Cost estimates: automation/model-run-costs.json
"""

HEADER = f"""NonExecAI — Activity, Cost & Prompt Log (single file)
=====================================================
All timestamps UTC unless noted.
Append-only. Open in Notepad.

{PROMPT_SUMMARY}
RUN ENTRIES
-----------
Format:
  [TIMESTAMP] PHASE | MODEL | RUNNER | USD | ACTIVITY | PROMPT

"""


def _load_costs() -> dict:
    if not COSTS_JSON.exists():
        return {"models": {}, "phase_model_map": {"odd": {}, "even": {}}}
    return json.loads(COSTS_JSON.read_text(encoding="utf-8"))


def _day_parity(day: int | None = None) -> str:
    d = day if day is not None else datetime.now(timezone.utc).day
    return "odd" if d % 2 == 1 else "even"


def model_for_phase(phase: str, now: datetime | None = None) -> tuple[str, str, float]:
    now = now or datetime.now(timezone.utc)
    cfg = _load_costs()
    parity = _day_parity(now.day)
    slug = cfg.get("phase_model_map", {}).get(parity, {}).get(phase.upper(), "gemini-2.5-flash")
    meta = cfg.get("models", {}).get(slug, {"label": slug, "est_usd": 0.0})
    return slug, meta.get("label", slug), float(meta.get("est_usd", 0.0))


def prompt_explanation(phase: str, model_slug: str, model_label: str, runner: str) -> str:
    phase = phase.upper()
    if phase == "DAWN":
        focus = "DAWN block: scan regulatory/practitioner sources, competitive gaps, reports/dawn-*.md"
    elif phase == "AFTERNOON":
        focus = "AFTERNOON block: content pages + registry entries + authority artifact"
    else:
        focus = f"{phase} block per governance-authority-agent.md"
    return (
        f"governance-authority-agent.md -> {focus}; "
        f"model={model_label} ({model_slug}); runner={runner}"
    )


def append_unified_entry(
    phase: str,
    activity: str,
    *,
    runner: str = "github-actions",
    model_slug: str | None = None,
    model_label: str | None = None,
    cost_usd: float | None = None,
    notes: str = "",
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    phase_u = phase.upper()

    if model_slug is None or cost_usd is None:
        auto_slug, auto_label, auto_cost = model_for_phase(phase_u, now)
        model_slug = model_slug or auto_slug
        model_label = model_label or auto_label
        if runner == "github-actions":
            gemini = _load_costs().get("models", {}).get("gemini-2.5-flash", {})
            model_slug = "gemini-2.5-flash"
            model_label = gemini.get("label", "Gemini 2.5 Flash")
            cost_usd = float(gemini.get("est_usd", 0.02))
        else:
            cost_usd = cost_usd if cost_usd is not None else auto_cost

    model_label = model_label or model_slug
    prompt = prompt_explanation(phase_u, model_slug, model_label, runner)
    note_bit = f" ({notes})" if notes else ""
    activity_clean = activity.replace("\n", " ").strip() + note_bit

    line = (
        f"[{ts}] {phase_u} | {model_label} ({model_slug}) | {runner} | "
        f"USD {cost_usd:.2f} | {activity_clean} | PROMPT: {prompt}\n"
    )

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not UNIFIED_LOG.exists():
        UNIFIED_LOG.write_text(HEADER, encoding="utf-8")
    with UNIFIED_LOG.open("a", encoding="utf-8") as f:
        f.write(line)

    # Keep legacy cost file in sync (cost column only)
    from log_cycle_cost import append_cost_line

    append_cost_line(
        phase_u,
        runner=runner,
        model_slug=model_slug,
        model_label=model_label,
        cost_usd=cost_usd,
        notes=notes,
        now=now,
    )

    return line.strip()


def daily_total(date_str: str | None = None) -> float:
    prefix = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not UNIFIED_LOG.exists():
        return 0.0
    total = 0.0
    for raw in UNIFIED_LOG.read_text(encoding="utf-8").splitlines():
        if not raw.startswith(f"[{prefix}"):
            continue
        if "USD " in raw:
            try:
                part = raw.split("USD ", 1)[1].split(" ", 1)[0]
                total += float(part)
            except ValueError:
                pass
    return total


def append_ranking_assessment(assessment_text: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not UNIFIED_LOG.exists():
        UNIFIED_LOG.write_text(HEADER, encoding="utf-8")
    block = f"\n=== AUTHORITY RANKING ASSESSMENT ({ts} UTC) ===\n{assessment_text.strip()}\n=== END ASSESSMENT ===\n\n"
    with UNIFIED_LOG.open("a", encoding="utf-8") as f:
        f.write(block)


if __name__ == "__main__":
    phase = os.environ.get("GOVERNANCE_PHASE", "DAWN").upper()
    if phase == "AUTO":
        from run_governance_phase import current_phase

        phase = current_phase()
    activity = os.environ.get(
        "ACTIVITY_SUMMARY",
        "Governance runner executed; see meta/run-log.md and reports/",
    )
    line = append_unified_entry(
        phase,
        activity,
        runner=os.environ.get("COST_RUNNER", "github-actions"),
        notes=os.environ.get("COST_NOTES", ""),
        cost_usd=float(os.environ["COST_USD"]) if os.environ.get("COST_USD") else None,
    )
    print(line)
    print(f"Daily total: USD {daily_total():.2f}")
    print(f"Log: {UNIFIED_LOG}")
