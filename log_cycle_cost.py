#!/usr/bin/env python3
"""Append prompt-cycling cost lines to NonExecAI Cost Cycling/prompt-cycling-costs.txt"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COST_DIR = ROOT / "NonExecAI Cost Cycling"
COST_FILE = COST_DIR / "prompt-cycling-costs.txt"
COSTS_JSON = ROOT / "automation" / "model-run-costs.json"

HEADER = """NonExecAI Prompt Cycling — Cost Log
=====================================
One line per run. All times UTC.
Format: YYYY-MM-DD HH:MM:SS | PHASE | MODEL | RUNNER | USD amount | notes

"""


def _load_costs() -> dict:
    if not COSTS_JSON.exists():
        return {"models": {}, "phase_model_map": {"odd": {}, "even": {}}}
    return json.loads(COSTS_JSON.read_text(encoding="utf-8"))


def _day_parity(day: int | None = None) -> str:
    d = day if day is not None else datetime.now(timezone.utc).day
    return "odd" if d % 2 == 1 else "even"


def model_for_phase(phase: str, now: datetime | None = None) -> tuple[str, str, float]:
    """Return (model_slug, model_label, est_usd) for phase on current day parity."""
    now = now or datetime.now(timezone.utc)
    cfg = _load_costs()
    parity = _day_parity(now.day)
    slug = cfg.get("phase_model_map", {}).get(parity, {}).get(phase.upper(), "gemini-2.5-flash")
    meta = cfg.get("models", {}).get(slug, {"label": slug, "est_usd": 0.0})
    return slug, meta.get("label", slug), float(meta.get("est_usd", 0.0))


def append_cost_line(
    phase: str,
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

    if model_slug is None or cost_usd is None:
        auto_slug, auto_label, auto_cost = model_for_phase(phase, now)
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
    note_suffix = f" | {notes}" if notes else ""
    line = (
        f"{ts} | {phase.upper()} | {model_label} ({model_slug}) | "
        f"{runner} | USD {cost_usd:.2f}{note_suffix}\n"
    )

    COST_DIR.mkdir(parents=True, exist_ok=True)
    if not COST_FILE.exists():
        COST_FILE.write_text(HEADER, encoding="utf-8")
    with COST_FILE.open("a", encoding="utf-8") as f:
        f.write(line)

    return line.strip()


def daily_total_for_date(date_str: str | None = None) -> float:
    """Sum USD amounts for lines matching date prefix YYYY-MM-DD."""
    if not COST_FILE.exists():
        return 0.0
    prefix = (date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")) + " "
    total = 0.0
    for raw in COST_FILE.read_text(encoding="utf-8").splitlines():
        if not raw.startswith(prefix):
            continue
        if "USD " in raw:
            try:
                part = raw.split("USD ", 1)[1].split(" ", 1)[0]
                total += float(part)
            except ValueError:
                pass
    return total


if __name__ == "__main__":
    import sys

    phase = os.environ.get("GOVERNANCE_PHASE", "DAWN").upper()
    if phase == "AUTO":
        from run_governance_phase import current_phase

        phase = current_phase()
    runner = os.environ.get("COST_RUNNER", "github-actions")
    notes = os.environ.get("COST_NOTES", "")
    actual = os.environ.get("COST_USD")
    line = append_cost_line(
        phase,
        runner=runner,
        cost_usd=float(actual) if actual else None,
        notes=notes,
    )
    day_total = daily_total_for_date()
    print(line)
    print(f"Daily total ({datetime.now(timezone.utc).date()}): USD {day_total:.2f}")
    sys.exit(0)
