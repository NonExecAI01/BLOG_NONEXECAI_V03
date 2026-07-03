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
        print("Cursor quota OK — no alert sent.")
        return 0

    state = load_state()
    if not force and already_alerted(account, state):
        print(f"Quota exhausted ({reason}) but alert already sent this billing cycle.")
        return 0

    recipients = alert_recipients(account)
    if dry_run:
        print(f"DRY RUN: would email {', '.join(recipients)}")
        print(f"Subject: {ALERT_MESSAGE}")
        print(f"Reason: {reason}")
        return 0

    sent_to = send_alert_email(account, reason)
    save_state(
        {
            "last_alert_billing_reset": account.get("billing_cycle_reset"),
            "last_alert_at": datetime.now(timezone.utc).isoformat(),
            "last_alert_reason": reason,
            "recipients": sent_to,
        }
    )
    print(f"Alert sent to: {', '.join(sent_to)}")
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
    print(f"Cleared tokens_exhausted and alert state in {account_path.parent.name}/")


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
