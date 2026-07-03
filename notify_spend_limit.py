#!/usr/bin/env python3
"""Email alert when Cursor tokens or on-demand spend limit is exhausted."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
DEFAULT_ACCOUNT_JSON = ROOT / "automation" / "cursor-account.json"
STATE_FILE = ROOT / "NonExecAI Cost Cycling" / ".spend-limit-alert-state.json"
CURSOR_RULE_REL = Path(".cursor/rules/spend-limit-alert.mdc")
CURSOR_NOTE_REL = Path("automation/CURSOR-SPEND-LIMIT-NOTE.md")
ALERT_MESSAGE = "INCREASE SPEND LIMIT ON CURSOR"
DEFAULT_RECIPIENTS = ["et@edgephone.ai", "et@non-exec.ai"]


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


def alert_recipients(account: dict[str, Any]) -> list[str]:
    alerts = account.get("spend_limit_alerts", {})
    configured = alerts.get("recipients")
    if configured:
        return list(configured)
    return DEFAULT_RECIPIENTS.copy()


def quota_exhausted(account: dict[str, Any]) -> tuple[bool, str]:
    if account.get("tokens_exhausted") is True:
        return True, "tokens_exhausted flag set in cursor-account.json"

    if os.environ.get("CURSOR_TOKENS_EXHAUSTED", "").strip() in {"1", "true", "yes"}:
        return True, "CURSOR_TOKENS_EXHAUSTED environment variable set"

    usage = account.get("usage_included_percent", {})
    api_pct = float(usage.get("api", 0))
    total_pct = float(usage.get("total", 0))
    spent = float(account.get("on_demand_spent_usd", 0))
    limit = float(account.get("on_demand_limit_usd", 20))

    if spent >= limit > 0:
        return True, f"on-demand spend limit reached ({spent:.2f}/{limit:.2f} USD)"

    included_exhausted = api_pct >= 100 or total_pct >= 100
    if included_exhausted and limit <= 0:
        return True, f"included usage exhausted (API {api_pct}%, total {total_pct}%) with no on-demand budget"

    if included_exhausted and spent >= limit:
        return True, (
            f"included usage exhausted (API {api_pct}%, total {total_pct}%) "
            f"and on-demand cap reached ({spent:.2f}/{limit:.2f} USD)"
        )

    return False, ""


def already_alerted(account: dict[str, Any], state: dict[str, Any]) -> bool:
    billing_reset = account.get("billing_cycle_reset", "")
    if not billing_reset:
        return False
    return state.get("last_alert_billing_reset") == billing_reset


def build_email_body(account: dict[str, Any], reason: str) -> str:
    usage = account.get("usage_included_percent", {})
    return "\n".join(
        [
            ALERT_MESSAGE,
            "",
            f"Account: {account.get('cursor_account', 'et@edgephone.ai')}",
            f"Plan: {account.get('cursor_plan', 'Pro+')}",
            f"Billing reset: {account.get('billing_cycle_reset', 'n/a')}",
            f"Included usage: total {usage.get('total', '?')}% | auto {usage.get('auto', '?')}% | API {usage.get('api', '?')}%",
            f"On-demand: USD {account.get('on_demand_spent_usd', 0)}/{account.get('on_demand_limit_usd', 20)}",
            f"Trigger: {reason}",
            "",
            "Update usage in automation/cursor-account.json after increasing the Cursor spend limit.",
        ]
    )


def cursor_note_roots(account_path: Path) -> list[Path]:
    repo_root = account_path.resolve().parent.parent
    roots = [repo_root]
    sibling = repo_root.parent / "aimodelpromptneai"
    if sibling.is_dir() and sibling not in roots:
        roots.append(sibling)
    return roots


def build_cursor_rule(account: dict[str, Any], reason: str) -> str:
    usage = account.get("usage_included_percent", {})
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""---
description: Cursor API tokens or on-demand spend limit exhausted — action required
alwaysApply: true
---

# {ALERT_MESSAGE}

**Action required before running Cloud Agent automations.**

- Account: `{account.get("cursor_account", "et@edgephone.ai")}`
- Plan: {account.get("cursor_plan", "Pro+")}
- Billing reset: {account.get("billing_cycle_reset", "n/a")}
- Included usage: total {usage.get("total", "?")}% | auto {usage.get("auto", "?")}% | API {usage.get("api", "?")}%
- On-demand: USD {account.get("on_demand_spent_usd", 0)}/{account.get("on_demand_limit_usd", 20)}
- Trigger: {reason}
- Updated: {ts}

Increase the on-demand spend limit in Cursor billing settings for **et@edgephone.ai**, then run:

`python notify_spend_limit.py --clear`

Also update `automation/cursor-account.json` usage fields from the Cursor dashboard.
"""


def build_cursor_note_markdown(account: dict[str, Any], reason: str) -> str:
    usage = account.get("usage_included_percent", {})
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""# {ALERT_MESSAGE}

This file is written automatically when Cursor tokens or the on-demand spend cap is exhausted
and email alerts are unavailable or failed.

| Field | Value |
|-------|-------|
| Account | {account.get("cursor_account", "et@edgephone.ai")} |
| Plan | {account.get("cursor_plan", "Pro+")} |
| Billing reset | {account.get("billing_cycle_reset", "n/a")} |
| Included usage | total {usage.get("total", "?")}% / auto {usage.get("auto", "?")}% / API {usage.get("api", "?")}% |
| On-demand | USD {account.get("on_demand_spent_usd", 0)} / {account.get("on_demand_limit_usd", 20)} |
| Trigger | {reason} |
| Updated | {ts} |

## What to do

1. Open Cursor → Settings → Billing for **et@edgephone.ai**
2. Increase the on-demand spend limit
3. Update `automation/cursor-account.json` from the dashboard
4. Clear this alert: `python notify_spend_limit.py --clear`

Email fallback recipients (when configured): et@edgephone.ai, et@non-exec.ai
"""


def write_cursor_notes(account_path: Path, account: dict[str, Any], reason: str) -> list[Path]:
    written: list[Path] = []
    rule_body = build_cursor_rule(account, reason)
    note_body = build_cursor_note_markdown(account, reason)
    for root in cursor_note_roots(account_path):
        rule_path = root / CURSOR_RULE_REL
        note_path = root / CURSOR_NOTE_REL
        rule_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        rule_path.write_text(rule_body, encoding="utf-8")
        note_path.write_text(note_body, encoding="utf-8")
        written.extend([rule_path, note_path])
    return written


def clear_cursor_notes(account_path: Path = DEFAULT_ACCOUNT_JSON) -> None:
    for root in cursor_note_roots(account_path):
        for rel in (CURSOR_RULE_REL, CURSOR_NOTE_REL):
            path = root / rel
            if path.exists():
                path.unlink()


def email_configured() -> bool:
    if os.environ.get("RESEND_API_KEY", "").strip():
        return True
    return bool(os.environ.get("SMTP_HOST", "").strip())


def send_via_resend(
    *,
    api_key: str,
    from_email: str,
    to: list[str],
    subject: str,
    body: str,
) -> None:
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_email,
            "to": to,
            "subject": subject,
            "text": body,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Resend API error {response.status_code}: {response.text}")


def send_via_smtp(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    from_email: str,
    to: list[str],
    subject: str,
    body: str,
    use_tls: bool,
) -> None:
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


def send_alert_email(account: dict[str, Any], reason: str) -> list[str]:
    alerts = account.get("spend_limit_alerts", {})
    subject = alerts.get("subject", ALERT_MESSAGE)
    body = build_email_body(account, reason)
    recipients = alert_recipients(account)

    from_email = (
        os.environ.get("ALERT_FROM_EMAIL")
        or os.environ.get("SMTP_FROM")
        or alerts.get("from_email")
        or "Non-Exec.AI Alerts <alerts@non-exec.ai>"
    )

    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if resend_key:
        send_via_resend(
            api_key=resend_key,
            from_email=from_email,
            to=recipients,
            subject=subject,
            body=body,
        )
        return recipients

    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    if smtp_host:
        send_via_smtp(
            host=smtp_host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USER", "").strip(),
            password=os.environ.get("SMTP_PASS", "").strip(),
            from_email=from_email,
            to=recipients,
            subject=subject,
            body=body,
            use_tls=os.environ.get("SMTP_USE_TLS", "true").lower() != "false",
        )
        return recipients

    raise RuntimeError(
        "No email transport configured. Set RESEND_API_KEY or SMTP_HOST (+ SMTP_USER/SMTP_PASS)."
    )


def check_and_notify(
    account_path: Path = DEFAULT_ACCOUNT_JSON,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    account = load_account(account_path)
    exhausted, reason = quota_exhausted(account)
    if not exhausted:
        clear_cursor_notes(account_path)
        print("Cursor quota OK — no alert needed.")
        return 0

    state = load_state()
    if dry_run:
        print(f"DRY RUN: quota exhausted — {reason}")
        print(f"Would write Cursor rule: {CURSOR_RULE_REL}")
        print(f"Would write Cursor note: {CURSOR_NOTE_REL}")
        if email_configured():
            print(f"Would email: {', '.join(alert_recipients(account))}")
        else:
            print("Email not configured — Cursor note would be the only alert.")
        print(f"Subject/body: {ALERT_MESSAGE}")
        return 0

    note_paths = write_cursor_notes(account_path, account, reason)
    print(f"Cursor note written ({len(note_paths)} files): {ALERT_MESSAGE}")

    if not force and already_alerted(account, state):
        print(f"Quota exhausted ({reason}); email already sent this billing cycle.")
        return 0

    if not email_configured():
        save_state(
            {
                "last_alert_billing_reset": account.get("billing_cycle_reset"),
                "last_alert_at": datetime.now(timezone.utc).isoformat(),
                "last_alert_reason": reason,
                "last_alert_method": "cursor-note",
            }
        )
        print("Email not configured — using Cursor rule + note only.")
        return 0

    try:
        sent_to = send_alert_email(account, reason)
    except Exception as exc:
        save_state(
            {
                "last_alert_billing_reset": account.get("billing_cycle_reset"),
                "last_alert_at": datetime.now(timezone.utc).isoformat(),
                "last_alert_reason": reason,
                "last_alert_method": "cursor-note",
                "email_error": str(exc),
            }
        )
        print(f"Email failed ({exc}). Cursor note is active.")
        return 0

    save_state(
        {
            "last_alert_billing_reset": account.get("billing_cycle_reset"),
            "last_alert_at": datetime.now(timezone.utc).isoformat(),
            "last_alert_reason": reason,
            "last_alert_method": "email+cursor-note",
            "recipients": sent_to,
        }
    )
    print(f"Email sent to: {', '.join(sent_to)}")
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
    clear_cursor_notes(account_path)
    print(f"Cleared tokens_exhausted, alert state, and Cursor notes.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Cursor spend-limit alert emails.")
    parser.add_argument(
        "--account-json",
        type=Path,
        default=DEFAULT_ACCOUNT_JSON,
        help="Path to cursor-account.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Evaluate quota and send alert if tokens/spend limit exhausted",
    )
    parser.add_argument("--force", action="store_true", help="Send even if already alerted this cycle")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without sending email")
    parser.add_argument(
        "--mark-exhausted",
        action="store_true",
        help="Set tokens_exhausted=true then run --check",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear tokens_exhausted flag and alert dedupe state after limit increase",
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
