#!/usr/bin/env python3
"""Cursor-only alert when tokens or on-demand spend limit is exhausted."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_ACCOUNT_JSON = ROOT / "automation" / "cursor-account.json"
STATE_FILE = ROOT / "NonExecAI Cost Cycling" / ".spend-limit-alert-state.json"
CURSOR_RULE_REL = Path(".cursor/rules/spend-limit-alert.mdc")
CURSOR_NOTE_REL = Path("automation/CURSOR-SPEND-LIMIT-NOTE.md")
CURSOR_UNDO_RULE_REL = Path(".cursor/rules/spend-limit-resolved.mdc")
CURSOR_UNDO_NOTE_REL = Path("automation/CURSOR-SPEND-LIMIT-RESOLVED.md")
DEFAULT_ALERT_MESSAGE = "INCREASE SPEND LIMIT ON CURSOR"
DEFAULT_UNDO_MESSAGE = "UNDO - CURSOR SPEND LIMIT RESOLVED"


def load_account(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Account config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def alert_config(account: dict[str, Any]) -> dict[str, Any]:
    return account.get("cursor_alerts") or account.get("spend_limit_alerts") or {}


def alert_message(account: dict[str, Any]) -> str:
    return alert_config(account).get("message") or DEFAULT_ALERT_MESSAGE


def undo_message(account: dict[str, Any]) -> str:
    return alert_config(account).get("undo_message") or DEFAULT_UNDO_MESSAGE


def trigger_thresholds(account: dict[str, Any]) -> dict[str, float]:
    triggers = alert_config(account).get("trigger") or {}
    return {
        "api_percent": float(triggers.get("api_percent", 100)),
        "total_percent": float(triggers.get("total_percent", 100)),
        "on_demand_spent_usd": float(
            triggers.get("on_demand_spent_usd", account.get("on_demand_limit_usd", 20))
        ),
    }


def undo_thresholds(account: dict[str, Any]) -> dict[str, float]:
    undo = alert_config(account).get("undo") or {}
    limit = float(account.get("on_demand_limit_usd", 20))
    return {
        "api_percent_below": float(undo.get("api_percent_below", 90)),
        "total_percent_below": float(undo.get("total_percent_below", 90)),
        "on_demand_spent_usd_below": float(undo.get("on_demand_spent_usd_below", max(limit - 5, 0))),
    }


def usage_values(account: dict[str, Any]) -> dict[str, float]:
    usage = account.get("usage_included_percent", {})
    return {
        "api": float(usage.get("api", 0)),
        "total": float(usage.get("total", 0)),
        "spent": float(account.get("on_demand_spent_usd", 0)),
        "limit": float(account.get("on_demand_limit_usd", 20)),
    }


def should_alert(account: dict[str, Any]) -> tuple[bool, str]:
    if account.get("tokens_exhausted") is True:
        return True, "tokens_exhausted flag set in cursor-account.json"

    if os.environ.get("CURSOR_TOKENS_EXHAUSTED", "").strip().lower() in {"1", "true", "yes"}:
        return True, "CURSOR_TOKENS_EXHAUSTED environment variable set"

    values = usage_values(account)
    thresholds = trigger_thresholds(account)

    if values["spent"] >= thresholds["on_demand_spent_usd"] > 0:
        return True, f"on-demand spend limit reached ({values['spent']:.2f}/{values['limit']:.2f} USD)"

    if values["api"] >= thresholds["api_percent"]:
        return True, f"API included usage at {values['api']:.0f}% (trigger {thresholds['api_percent']:.0f}%)"

    if values["total"] >= thresholds["total_percent"]:
        return True, f"total included usage at {values['total']:.0f}% (trigger {thresholds['total_percent']:.0f}%)"

    included_exhausted = values["api"] >= 100 or values["total"] >= 100
    if included_exhausted and values["limit"] <= 0:
        return True, "included usage exhausted with no on-demand budget"

    if included_exhausted and values["spent"] >= values["limit"]:
        return True, (
            f"included usage exhausted (API {values['api']:.0f}%, total {values['total']:.0f}%) "
            f"and on-demand cap reached ({values['spent']:.2f}/{values['limit']:.2f} USD)"
        )

    return False, ""


def should_undo_alert(account: dict[str, Any], state: dict[str, Any]) -> bool:
    if not state.get("alert_active"):
        return False
    if account.get("tokens_exhausted") is True:
        return False

    values = usage_values(account)
    undo = undo_thresholds(account)
    return (
        values["api"] < undo["api_percent_below"]
        and values["total"] < undo["total_percent_below"]
        and values["spent"] < undo["on_demand_spent_usd_below"]
    )


def cursor_note_roots(account_path: Path) -> list[Path]:
    repo_root = account_path.resolve().parent.parent
    roots = [repo_root]
    sibling = repo_root.parent / "aimodelpromptneai"
    if sibling.is_dir() and sibling not in roots:
        roots.append(sibling)
    return roots


def build_cursor_rule(account: dict[str, Any], reason: str) -> str:
    values = usage_values(account)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = alert_message(account)
    return f"""---
description: Cursor API tokens or on-demand spend limit exhausted — action required
alwaysApply: true
---

# {message}

**Action required before running Cloud Agent automations.**

- Account: `{account.get("cursor_account", "et@edgephone.ai")}`
- Plan: {account.get("cursor_plan", "Pro+")}
- Billing reset: {account.get("billing_cycle_reset", "n/a")}
- Included usage: total {values["total"]:.0f}% | API {values["api"]:.0f}%
- On-demand: USD {values["spent"]:.2f}/{values["limit"]:.2f}
- Trigger: {reason}
- Updated: {ts}

Increase the on-demand spend limit in Cursor billing settings for **et@edgephone.ai**, then run:

`python notify_spend_limit.py --clear`

Also update `automation/cursor-account.json` usage fields from the Cursor dashboard.
"""


def build_cursor_note_markdown(account: dict[str, Any], reason: str) -> str:
    values = usage_values(account)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = alert_message(account)
    return f"""# {message}

Cursor-only alert (email alerts disabled). Written when tokens or the on-demand spend cap is hit.

| Field | Value |
|-------|-------|
| Account | {account.get("cursor_account", "et@edgephone.ai")} |
| Plan | {account.get("cursor_plan", "Pro+")} |
| Billing reset | {account.get("billing_cycle_reset", "n/a")} |
| Included usage | total {values["total"]:.0f}% / API {values["api"]:.0f}% |
| On-demand | USD {values["spent"]:.2f} / {values["limit"]:.2f} |
| Trigger | {reason} |
| Updated | {ts} |

## What to do

1. Open Cursor → Settings → Billing for **et@edgephone.ai**
2. Increase the on-demand spend limit
3. Update `automation/cursor-account.json` from the dashboard
4. Clear this alert: `python notify_spend_limit.py --clear`

Undo runs automatically when usage drops below undo thresholds in `cursor-account.json`.
"""


def build_undo_cursor_rule(account: dict[str, Any]) -> str:
    values = usage_values(account)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = undo_message(account)
    return f"""---
description: Cursor spend limit back within safe range
alwaysApply: true
---

# {message}

Cursor usage is back within limits for **{account.get("cursor_account", "et@edgephone.ai")}**.

- Included usage: total {values["total"]:.0f}% | API {values["api"]:.0f}%
- On-demand: USD {values["spent"]:.2f}/{values["limit"]:.2f}
- Updated: {ts}

Cloud Agent automations may run again. This resolved notice is removed on the next quota check.
"""


def build_undo_cursor_note(account: dict[str, Any]) -> str:
    values = usage_values(account)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = undo_message(account)
    return f"""# {message}

| Field | Value |
|-------|-------|
| Account | {account.get("cursor_account", "et@edgephone.ai")} |
| Included usage | total {values["total"]:.0f}% / API {values["api"]:.0f}% |
| On-demand | USD {values["spent"]:.2f} / {values["limit"]:.2f} |
| Updated | {ts} |

No action required. Remove manually with `python notify_spend_limit.py --clear` if still visible.
"""


def _write_paths(account_path: Path, paths: dict[Path, str]) -> list[Path]:
    written: list[Path] = []
    for root in cursor_note_roots(account_path):
        for rel, body in paths.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            written.append(target)
    return written


def _remove_paths(account_path: Path, rel_paths: list[Path]) -> None:
    for root in cursor_note_roots(account_path):
        for rel in rel_paths:
            path = root / rel
            if path.exists():
                path.unlink()


def write_cursor_alert(account_path: Path, account: dict[str, Any], reason: str) -> list[Path]:
    _remove_paths(
        account_path,
        [CURSOR_UNDO_RULE_REL, CURSOR_UNDO_NOTE_REL],
    )
    return _write_paths(
        account_path,
        {
            CURSOR_RULE_REL: build_cursor_rule(account, reason),
            CURSOR_NOTE_REL: build_cursor_note_markdown(account, reason),
        },
    )


def write_cursor_undo(account_path: Path, account: dict[str, Any]) -> list[Path]:
    _remove_paths(account_path, [CURSOR_RULE_REL, CURSOR_NOTE_REL])
    return _write_paths(
        account_path,
        {
            CURSOR_UNDO_RULE_REL: build_undo_cursor_rule(account),
            CURSOR_UNDO_NOTE_REL: build_undo_cursor_note(account),
        },
    )


def clear_all_cursor_notes(account_path: Path = DEFAULT_ACCOUNT_JSON) -> None:
    _remove_paths(
        account_path,
        [CURSOR_RULE_REL, CURSOR_NOTE_REL, CURSOR_UNDO_RULE_REL, CURSOR_UNDO_NOTE_REL],
    )


def check_and_notify(
    account_path: Path = DEFAULT_ACCOUNT_JSON,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    account = load_account(account_path)
    state = load_state()
    alert, reason = should_alert(account)

    if not alert and should_undo_alert(account, state):
        if dry_run:
            print(f"DRY RUN: would undo Cursor alert — {undo_message(account)}")
            return 0
        write_cursor_undo(account_path, account)
        save_state(
            {
                "alert_active": False,
                "last_undo_at": datetime.now(timezone.utc).isoformat(),
                "last_undo_billing_reset": account.get("billing_cycle_reset"),
            }
        )
        print(f"Cursor alert undone: {undo_message(account)}")
        return 0

    if not alert:
        if state.get("alert_active"):
            clear_all_cursor_notes(account_path)
            save_state({"alert_active": False})
        else:
            clear_all_cursor_notes(account_path)
        print("Cursor quota OK — no alert needed.")
        return 0

    if dry_run:
        print(f"DRY RUN: would write Cursor alert — {reason}")
        print(f"Rule: {CURSOR_RULE_REL}")
        print(f"Note: {CURSOR_NOTE_REL}")
        print(f"Message: {alert_message(account)}")
        return 0

    if not force and state.get("alert_active") and state.get("last_alert_reason") == reason:
        print(f"Cursor alert already active ({reason}).")
        return 0

    paths = write_cursor_alert(account_path, account, reason)
    save_state(
        {
            "alert_active": True,
            "last_alert_at": datetime.now(timezone.utc).isoformat(),
            "last_alert_reason": reason,
            "last_alert_billing_reset": account.get("billing_cycle_reset"),
            "last_alert_method": "cursor-only",
        }
    )
    print(f"Cursor alert written ({len(paths)} files): {alert_message(account)}")
    print(f"Reason: {reason}")
    return 0


def mark_tokens_exhausted(account_path: Path = DEFAULT_ACCOUNT_JSON) -> None:
    account = load_account(account_path)
    account["tokens_exhausted"] = True
    account_path.write_text(json.dumps(account, indent=2) + "\n", encoding="utf-8")
    print(f"Set tokens_exhausted=true in {account_path}")


def clear_tokens_exhausted(account_path: Path = DEFAULT_ACCOUNT_JSON) -> None:
    account = load_account(account_path)
    account.pop("tokens_exhausted", None)
    account_path.write_text(json.dumps(account, indent=2) + "\n", encoding="utf-8")
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    clear_all_cursor_notes(account_path)
    print("Cleared tokens_exhausted, alert state, and all Cursor alert/undo notes.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor-only spend-limit alerts.")
    parser.add_argument(
        "--account-json",
        type=Path,
        default=DEFAULT_ACCOUNT_JSON,
        help="Path to cursor-account.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Evaluate quota and write or undo Cursor alert",
    )
    parser.add_argument("--force", action="store_true", help="Rewrite alert even if already active")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing files")
    parser.add_argument(
        "--mark-exhausted",
        action="store_true",
        help="Set tokens_exhausted=true then run --check",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear tokens_exhausted flag and all Cursor alert/undo files",
    )
    args = parser.parse_args()

    if args.clear:
        clear_tokens_exhausted(args.account_json)
        return 0

    if args.mark_exhausted:
        mark_tokens_exhausted(args.account_json)

    if args.check or args.mark_exhausted:
        return check_and_notify(args.account_json, force=args.force, dry_run=args.dry_run)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
