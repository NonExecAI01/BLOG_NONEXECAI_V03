#!/usr/bin/env python3
"""Run one governance authority phase for non-exec.ai (GitHub Actions runner)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PHASES = [
    (6, "DAWN"),
    (16, "AFTERNOON"),
]

ROOT = Path(__file__).resolve().parent
REGISTRY_FILE = ROOT / "registry" / "agents-models.json"
RUN_LOG = ROOT / "meta" / "run-log.md"


def current_phase(now: datetime | None = None) -> str:
    forced = os.environ.get("GOVERNANCE_PHASE", "auto").upper()
    if forced in {"DAWN", "AFTERNOON"}:
        return forced
    hour = (now or datetime.now(timezone.utc)).hour
    phase = "MIDNIGHT"
    for h, name in PHASES:
        if hour >= h:
            phase = name
    return phase


def ensure_dirs() -> None:
    for d in ("registry/pages", "content", "reports", "briefings", "meta"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)


def append_run_log(phase: str, note: str) -> None:
    ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## {ts} — {phase}\n\n{note}\n"
    if RUN_LOG.exists():
        RUN_LOG.write_text(RUN_LOG.read_text(encoding="utf-8") + entry, encoding="utf-8")
    else:
        RUN_LOG.write_text(f"# Governance Agent Run Log\n{entry}", encoding="utf-8")


def registry_count() -> int:
    if not REGISTRY_FILE.exists():
        return 0
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        return len(data.get("entries", []))
    except json.JSONDecodeError:
        return 0


def main() -> int:
    ensure_dirs()
    phase = current_phase()
    count = registry_count()
    append_run_log(
        phase,
        f"GitHub Actions governance runner executed.\n"
        f"- Registry entries on disk: {count}\n"
        f"- Primary automation: Cursor Cloud (8 prefills in aimodelpromptneai)\n",
    )

    from log_activity import append_unified_entry, daily_total

    run_notes = os.environ.get("GITHUB_RUN_ID", "")
    note = f"github run {run_notes}" if run_notes else "scheduled"
    registry_n = registry_count()
    append_unified_entry(
        phase,
        f"GitHub Actions governance run; registry entries={registry_n}",
        runner="github-actions",
        notes=note,
    )
    day_total = daily_total()

    print(f"Governance phase: {phase}")
    print(f"Registry entries: {count}")
    print(f"Cost logged. Daily total: USD {day_total:.2f}")

    try:
        from notify_spend_limit import check_and_notify

        check_and_notify()
    except Exception as exc:
        print(f"Quota alert check skipped: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
