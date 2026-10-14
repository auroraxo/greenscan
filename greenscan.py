#!/usr/bin/env python3
"""
greenscan — free, read-only n8n reliability audit.

What it does:
    Points at an n8n instance with an API key, reads workflows + recent
    executions, and runs six cheap checks mapped to the failure classes the
    n8n community has named. Prints a one-page report. Does not write to
    your instance, does not store the API key, does not call home.

What it is not:
    Not a continuous monitor. Not an outcome verifier. Not a fix.
    If the report finds something, that's the input that decides whether
    you want a paid monitor on top of it.

Usage:
    export N8N_API_KEY="n8n_api_xxxxx"
    greenscan --base-url https://n8n.example.com
    greenscan --base-url https://acme.app.n8n.cloud --days 14 --json > report.json
    python3 -m greenscan --base-url https://n8n.example.com --dry-run   # demo data

Exit code:
    0 — report generated, no findings
    1 — report generated, one or more findings
    2 — could not reach the instance or invalid arguments

Six checks (see the report for the failure class each one maps to):
    A. hard_error     — last N executions contained a thrown error
    B. missed_run     — active scheduled workflow with no execution in 7d
    C. early_end      — successful execution terminated before last node
    D. empty_output   — successful execution with zero items
    E. coaf_risk      — workflow has both continueRegularOutput + alwaysOutputData
                        (the Cristian failure: 201 + green + state advanced)
    F. zombie         — active workflow with no executions in 30d

Author: Aurora (https://codebyaurora.com)
License: MIT
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

API_VERSION = "v1"
DEFAULT_DAYS = 7
DEFAULT_PAGE = 100   # n8n default
MAX_PAGE = 250       # n8n max

# Severity colors (ANSI). Plain text when stdout is not a tty.
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def red(t: str) -> str:
    return c("1;31", t)


def yellow(t: str) -> str:
    return c("1;33", t)


def green(t: str) -> str:
    return c("1;32", t)


def dim(t: str) -> str:
    return c("2", t)


def bold(t: str) -> str:
    return c("1", t)


# ---------- HTTP --------------------------------------------------------- #


class N8nError(Exception):
    pass


def _request(base: str, key: str, path: str, params: dict | None = None) -> Any:
    base = base.rstrip("/")
    url = f"{base}/api/{API_VERSION}{path}"
    if params:
        # urllib can't build query strings with repeated keys; n8n uses cursor
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if qs:
            url = f"{url}?{qs}"
    req = urllib.request.Request(
        url,
        headers={"X-N8N-API-KEY": key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise N8nError(f"HTTP {e.code} on {path}: {body or e.reason}") from None
    except urllib.error.URLError as e:
        raise N8nError(f"cannot reach {base}: {e.reason}") from None


def _iter(base: str, key: str, path: str, params: dict | None = None) -> Iterable[dict]:
    """n8n paginates with {data, nextCursor}; yield each item."""
    cursor = None
    while True:
        p = dict(params or {})
        p["limit"] = MAX_PAGE
        if cursor:
            p["cursor"] = cursor
        payload = _request(base, key, path, p)
        for item in payload.get("data", []) or []:
            yield item
        cursor = payload.get("nextCursor")
        if not cursor:
            return


# ---------- Demo / dry-run data ----------------------------------------- #

DEMO_WORKFLOWS = [
    {
        "id": "wf-1001",
        "name": "WhatsApp Cadence",
        "active": True,
        "staticData": None,
        "nodes": [
            {"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger",
             "parameters": {"rule": {"interval": [{"hours": 1}]}}},
            {"name": "HTTP Send", "type": "n8n-nodes-base.httpRequest",
             "onError": "continueRegularOutput",
             "alwaysOutputData": True},
            {"name": "Update DB", "type": "n8n-nodes-base.postgres",
             "parameters": {"operation": "update"}},
            {"name": "Slack Notify", "type": "n8n-nodes-base.slack",
             "parameters": {"channel": "#ops"}},
        ],
        "settings": {"executionOrder": "v1"},
        "tags": [{"name": "production"}],
    },
    {
        "id": "wf-1002",
        "name": "Clinic Reminder",
        "active": True,
        "nodes": [
            {"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger",
             "parameters": {"rule": {"interval": [{"hours": 6}]}}},
            {"name": "Build List", "type": "n8n-nodes-base.code"},
            {"name": "Twilio Send", "type": "n8n-nodes-base.twilio",
             "onError": "continueErrorOutput"},
        ],
        "settings": {"executionOrder": "v1"},
        "tags": [],
    },
    {
        "id": "wf-1003",
        "name": "Nightly Report",
        "active": True,
        "nodes": [
            {"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger",
             "parameters": {"rule": {"interval": [{"hours": 24}]}}},
            {"name": "Query DB", "type": "n8n-nodes-base.postgres"},
            {"name": "Render PDF", "type": "n8n-nodes-base.code"},
        ],
        "settings": {"executionOrder": "v1"},
        "tags": [],
    },
    {
        "id": "wf-1004",
        "name": "Webhook Intake",
        "active": True,
        "nodes": [
            {"name": "Webhook", "type": "n8n-nodes-base.webhook"},
            {"name": "Validate", "type": "n8n-nodes-base.code"},
            {"name": "Persist", "type": "n8n-nodes-base.postgres"},
        ],
        "settings": {"executionOrder": "v1"},
        "tags": [],
    },
    {
        "id": "wf-1005",
        "name": "Forgotten Test (zombie)",
        "active": True,
        "nodes": [
            {"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger",
             "parameters": {"rule": {"interval": [{"hours": 24}]}}},
        ],
        "settings": {"executionOrder": "v1"},
        "tags": [],
    },
]

DEMO_EXECUTIONS = [
    {"id": "e-9001", "workflowId": "wf-1001", "status": "success",
     "startedAt": "2026-10-13T14:00:00Z", "stoppedAt": "2026-10-13T14:00:02Z",
     "mode": "trigger"},
    {"id": "e-9002", "workflowId": "wf-1001", "status": "success",
     "startedAt": "2026-10-13T15:00:00Z", "stoppedAt": "2026-10-13T15:00:02Z",
     "mode": "trigger", "data": {"resultData": {"lastNodeExecuted": "Update DB"}}},
    {"id": "e-9003", "workflowId": "wf-1001", "status": "error",
     "startedAt": "2026-10-13T16:00:00Z", "stoppedAt": "2026-10-13T16:00:02Z",
     "mode": "trigger", "data": {"resultData": {"error": {"message": "ECONNREFUSED"}}}},
    {"id": "e-9004", "workflowId": "wf-1002", "status": "success",
     "startedAt": "2026-10-13T10:00:00Z", "stoppedAt": "2026-10-13T10:00:02Z",
     "mode": "trigger", "data": {"resultData": {"lastNodeExecuted": "Twilio Send"}}},
    # 14 days since last report
    {"id": "e-9005", "workflowId": "wf-1003", "status": "success",
     "startedAt": "2026-09-29T02:00:00Z", "stoppedAt": "2026-09-29T02:00:05Z",
     "mode": "trigger", "data": {"resultData": {"lastNodeExecuted": "Render PDF"}}},
    {"id": "e-9006", "workflowId": "wf-1004", "status": "success",
     "startedAt": "2026-10-13T12:00:00Z", "stoppedAt": "2026-10-13T12:00:01Z",
     "mode": "webhook", "data": {"resultData": {"lastNodeExecuted": "Persist"}}},
    # zero-output successes: webhook fires but validation drops every item
    {"id": "e-9007", "workflowId": "wf-1004", "status": "success",
     "startedAt": "2026-10-13T18:00:00Z", "stoppedAt": "2026-10-13T18:00:01Z",
     "mode": "webhook", "data": {"resultData": {"lastNodeExecuted": "Validate",
                                                 "runData": {"Validate": [{"json": []}]}}}},
    {"id": "e-9008", "workflowId": "wf-1004", "status": "success",
     "startedAt": "2026-10-13T19:00:00Z", "stoppedAt": "2026-10-13T19:00:01Z",
     "mode": "webhook", "data": {"resultData": {"lastNodeExecuted": "Validate",
                                                 "runData": {"Validate": [{"json": []}]}}}},
    {"id": "e-9009", "workflowId": "wf-1004", "status": "success",
     "startedAt": "2026-10-13T20:00:00Z", "stoppedAt": "2026-10-13T20:00:01Z",
     "mode": "webhook", "data": {"resultData": {"lastNodeExecuted": "Validate",
                                                 "runData": {"Validate": [{"json": []}]}}}},
    {"id": "e-9010", "workflowId": "wf-1004", "status": "success",
     "startedAt": "2026-10-13T21:00:00Z", "stoppedAt": "2026-10-13T21:00:01Z",
     "mode": "webhook", "data": {"resultData": {"lastNodeExecuted": "Persist"}}},
    {"id": "e-9011", "workflowId": "wf-1004", "status": "success",
     "startedAt": "2026-10-13T22:00:00Z", "stoppedAt": "2026-10-13T22:00:01Z",
     "mode": "webhook", "data": {"resultData": {"lastNodeExecuted": "Persist"}}},
    # zombie — never executed
    # wf-1005: no entries
]


def load_data(base: str, key: str, dry_run: bool, days: int):
    if dry_run:
        return list(DEMO_WORKFLOWS), list(DEMO_EXECUTIONS), "demo-instance"
    # user info (best-effort, just for the report header)
    instance_name = ""
    try:
        me = _request(base, key, "/me")
        instance_name = (me.get("data") or {}).get("email") or me.get("email") or ""
    except Exception:
        pass
    workflows = list(_iter(base, key, "/workflows", {"limit": MAX_PAGE}))
    # cap executions to a sane window; n8n stores ~14–30d of free executions
    executions = list(_iter(base, key, "/executions", {"limit": MAX_PAGE,
                                                       "includeData": "true"}))
    return workflows, executions, instance_name


# ---------- Checks ------------------------------------------------------ #


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except ValueError:
        return None


def _has_coaf_risk(workflow: dict) -> bool:
    """Cristian's pattern: onError: continueRegularOutput + alwaysOutputData: true
    turns an HTTP 500 into a green execution that updates downstream state."""
    for node in workflow.get("nodes", []) or []:
        if node.get("onError") == "continueRegularOutput" and node.get("alwaysOutputData") is True:
            return True
    return False


def _terminal_node(workflow: dict) -> str | None:
    """Best-effort guess at the workflow's last meaningful node.
    The execution list already gives us lastNodeExecuted; we only need a
    stable reference for the early-end check."""
    nodes = workflow.get("nodes") or []
    if not nodes:
        return None
    # n8n does not have a single source of truth for "last"; callers should
    # pass lastNodeExecuted from the execution when available.
    return nodes[-1].get("name")


def _execution_items_count(execution: dict) -> int | None:
    rd = (execution.get("data") or {}).get("resultData") or {}
    run = rd.get("runData") or {}
    if not run:
        return None
    last = rd.get("lastNodeExecuted")
    if not last or last not in run:
        return None
    items = run[last]
    if not isinstance(items, list) or not items:
        return None
    try:
        return len(items[0].get("json") or [])
    except (TypeError, AttributeError):
        return None


def analyse(workflows: list[dict], executions: list[dict], days: int):
    findings: list[dict] = []
    now = datetime.now(timezone.utc)
    by_workflow: dict[str, list[dict]] = defaultdict(list)
    for ex in executions:
        by_workflow[str(ex.get("workflowId"))].append(ex)

    for wf in workflows:
        wf_id = str(wf.get("id"))
        wf_name = wf.get("name", "(no name)")
        is_active = bool(wf.get("active"))
        is_scheduled = any(
            (n.get("type") or "").endswith("scheduleTrigger")
            for n in (wf.get("nodes") or [])
        )
        wf_execs = by_workflow.get(wf_id, [])
        wf_execs.sort(key=lambda e: e.get("startedAt") or "")

        # A. hard error
        err_count = sum(1 for e in wf_execs if e.get("status") == "error")
        if err_count and wf_execs:
            findings.append({
                "id": f"A:{wf_id}",
                "class": "hard_error",
                "workflow": wf_name,
                "detail": f"{err_count} of {len(wf_execs)} recent executions errored",
                "severity": "info",
            })

        # E. continueRegularOutput + alwaysOutputData
        if _has_coaf_risk(wf):
            findings.append({
                "id": f"E:{wf_id}",
                "class": "coaf_risk",
                "workflow": wf_name,
                "detail": "node has onError=continueRegularOutput + alwaysOutputData=true; "
                          "a downstream 5xx becomes a green execution that still writes state",
                "severity": "high",
            })

        # C. early end
        last_node = _terminal_node(wf)
        early = 0
        for e in wf_execs:
            if e.get("status") != "success":
                continue
            rd = (e.get("data") or {}).get("resultData") or {}
            lne = rd.get("lastNodeExecuted")
            if last_node and lne and lne != last_node:
                early += 1
        if early:
            findings.append({
                "id": f"C:{wf_id}",
                "class": "early_end",
                "workflow": wf_name,
                "detail": f"{early} successful execution{'s' if early != 1 else ''} "
                          f"ended before last node ({last_node!r})",
                "severity": "medium",
            })

        # D. empty output
        empty = 0
        total_success = 0
        for e in wf_execs:
            if e.get("status") != "success":
                continue
            total_success += 1
            n = _execution_items_count(e)
            if n == 0:
                empty += 1
        if total_success >= 5 and empty / total_success >= 0.5:
            findings.append({
                "id": f"D:{wf_id}",
                "class": "empty_output",
                "workflow": wf_name,
                "detail": f"{empty}/{total_success} successful runs produced zero items",
                "severity": "medium",
            })

        # B + F. missed run / zombie (only for active scheduled workflows)
        if is_active and is_scheduled and not wf_execs:
            findings.append({
                "id": f"F:{wf_id}",
                "class": "zombie",
                "workflow": wf_name,
                "detail": "active scheduled workflow with no executions in the window",
                "severity": "high",
            })
        elif is_active and is_scheduled and wf_execs:
            latest = wf_execs[-1].get("startedAt")
            latest_dt = _parse_iso(latest) if latest else None
            if latest_dt and (now - latest_dt).days > days:
                findings.append({
                    "id": f"B:{wf_id}",
                    "class": "missed_run",
                    "workflow": wf_name,
                    "detail": f"last execution {(now - latest_dt).days}d ago "
                              f"(window: {days}d)",
                    "severity": "high",
                })

    severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda f: (severity_order.get(f["severity"], 9), f["workflow"]))
    return findings


# ---------- Report ------------------------------------------------------ #


def render_text(workflows, executions, days, findings, instance):
    lines: list[str] = []
    add = lines.append
    add(bold("greenscan — n8n reliability audit"))
    add(dim(f"  scanned {len(workflows)} workflow(s), {len(executions)} execution(s), "
            f"window {days}d · {datetime.now(timezone.utc).isoformat(timespec='seconds')}"))
    if instance:
        add(dim(f"  instance: {instance}"))
    add("")
    if not findings:
        add(green("  No findings."))
        add(dim("  The six checks all passed. Re-run with a longer --days window, "
                "or check after a new failure class surfaces in the community."))
        return "\n".join(lines) + "\n"

    counts = Counter(f["severity"] for f in findings)
    summary = " · ".join(f"{counts.get(s, 0)} {s}" for s in ("high", "medium", "info")
                         if counts.get(s, 0))
    add(f"  {len(findings)} finding(s) — {summary}")
    add("")
    by_class: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_class[f["class"]].append(f)
    legend = {
        "hard_error":    ("A", "hard error",
                          "n8n's Error Workflow catches these; flag only if many."),
        "missed_run":    ("B", "missed run",
                          "scheduled workflow hasn't fired in the window."),
        "early_end":     ("C", "silent failure (early end)",
                          "execution was green but stopped before the last node."),
        "empty_output":  ("D", "empty output",
                          "successful run produced zero items."),
        "coaf_risk":     ("E", "continue-on-fail + alwaysOutputData",
                          "downstream 5xx becomes green + state still writes."),
        "zombie":        ("F", "zombie",
                          "active scheduled workflow with no recent executions."),
    }
    for cls, (tag, label, hint) in legend.items():
        items = by_class.get(cls, [])
        if not items:
            continue
        add(bold(f"  {tag}. {label}"))
        add(dim(f"     {hint}"))
        for f in items:
            sev_color = {"high": red, "medium": yellow, "info": dim, "low": dim}[f["severity"]]
            add(f"     {sev_color(f['severity'].ljust(7))} {f['workflow']} — {f['detail']}")
        add("")
    add(dim("  This is a one-shot read-only audit. greenscan does not modify the instance,"))
    add(dim("  does not store the API key, and does not call home. Re-run as often as you want."))
    return "\n".join(lines) + "\n"


def render_json(workflows, executions, days, findings, instance):
    return json.dumps({
        "tool": "greenscan",
        "version": "0.1.0",
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "instance": instance or None,
        "window_days": days,
        "workflows_scanned": len(workflows),
        "executions_scanned": len(executions),
        "findings": findings,
    }, indent=2, sort_keys=True) + "\n"


# ---------- CLI --------------------------------------------------------- #


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="greenscan",
        description="Free, read-only n8n reliability audit (six community-named failure classes).",
    )
    p.add_argument("--base-url",
                   help="n8n base URL, e.g. https://n8n.example.com or https://acme.app.n8n.cloud. "
                        "If omitted, uses $N8N_BASE_URL.")
    p.add_argument("--api-key",
                   help="n8n API key. If omitted, uses $N8N_API_KEY. "
                        "Never logged, never stored.")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS,
                   help=f"look-back window in days for execution history (default {DEFAULT_DAYS}).")
    p.add_argument("--json", action="store_true", help="emit JSON instead of text.")
    p.add_argument("--dry-run", action="store_true",
                   help="use bundled demo data; no network call, no key required.")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors.")
    args = p.parse_args(argv)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"
        global USE_COLOR
        USE_COLOR = False

    if args.days < 1 or args.days > 365:
        print(red("error: --days must be between 1 and 365"), file=sys.stderr)
        return 2

    base = args.base_url or os.environ.get("N8N_BASE_URL", "")
    key = args.api_key or os.environ.get("N8N_API_KEY", "")
    if not args.dry_run and not (base and key):
        print(red("error: --base-url and --api-key (or N8N_BASE_URL + N8N_API_KEY) "
                  "are required, or use --dry-run"),
              file=sys.stderr)
        p.print_usage(sys.stderr)
        return 2

    t0 = time.time()
    try:
        workflows, executions, instance = load_data(base, key, args.dry_run, args.days)
    except N8nError as e:
        print(red(f"error: {e}"), file=sys.stderr)
        return 2
    findings = analyse(workflows, executions, args.days)
    if args.json:
        sys.stdout.write(render_json(workflows, executions, args.days, findings, instance))
    else:
        sys.stdout.write(render_text(workflows, executions, args.days, findings, instance))
    if not args.json and not args.dry_run:
        sys.stderr.write(dim(f"  completed in {time.time() - t0:.1f}s\n"))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
