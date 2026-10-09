#!/usr/bin/env python3
"""Run ReleaseProof as a release gate in CI.

Posts a change to a deployed orchestrator, renders the evidence, and exits
non-zero when the gate blocks — so a pipeline step fails on a regression that
ordinary verification would have let through.

Standard library only: CI runners should not need a dependency install to run
a gate, and a gate that fails because its own install broke is worse than no
gate at all.

    python3 ci/releaseproof_gate.py \\
        --api-url https://releaseproof-api-xxxx.run.app \\
        --stable-url https://my-service-stable.run.app \\
        --candidate-url https://my-service-candidate.run.app \\
        --request-path /api/v1/quote

Exit codes:
    0  PASS          the candidate may receive traffic
    1  BLOCK         a blocking experiment failed under fixed policy
    2  INCONCLUSIVE  evidence was insufficient (treated as failure by default)
    3  the gate itself could not run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

EXIT_PASS = 0
EXIT_BLOCK = 1
EXIT_INCONCLUSIVE = 2
EXIT_ERROR = 3

STATE = {True: "pass", False: "FAIL", None: "inconclusive"}


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=30, check=True
        ).stdout.strip()
    except Exception:
        return ""


def _default_diff(base: str | None) -> str:
    """Derive the change under test from the repository itself.

    A gate that has to be told what changed is just a test runner. Reading the
    diff is what makes the investigation specific to this release.
    """
    if base:
        diff = _git("diff", f"{base}...HEAD")
        if diff:
            return diff
    return _git("diff", "HEAD~1", "HEAD") or _git("show", "--format=", "HEAD")


def _default_summary() -> str:
    return _git("log", "-1", "--pretty=%s") or "Change under release verification"


def _post(url: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "ReleaseProof-CI/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def _annotate(level: str, message: str) -> None:
    """Emit a GitHub Actions annotation when running there, else a plain line."""
    one_line = message.replace("\n", " ")
    if os.getenv("GITHUB_ACTIONS") == "true":
        print(f"::{level}::{one_line}")
    else:
        print(f"[{level}] {one_line}")


def _write_summary(lines: list[str]) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass  # A summary is a nicety; never fail the gate over it.


def _render(ledger: dict, run_id: str, api_url: str) -> list[str]:
    verdict = ledger.get("verdict") or "UNKNOWN"
    icon = {"PASS": "✅", "BLOCK": "🛑", "INCONCLUSIVE": "⚠️"}.get(verdict, "❔")
    plan = ledger.get("plan") or {}

    lines = [
        f"## {icon} ReleaseProof: {verdict}",
        "",
        f"**Planner:** `{plan.get('planner', 'unknown')}` · "
        f"**Mode:** `{plan.get('analysis_mode', 'guarded')}` · "
        f"**Evidence:** [`{run_id[:8]}`]({api_url}/api/runs/{run_id})",
        "",
        f"> {plan.get('risk_summary', 'No risk summary reported.')}",
        "",
        "| | Experiment | Finding |",
        "|---|---|---|",
    ]

    for item in ledger.get("evidence", []):
        mark = {True: "✅", False: "❌", None: "⚠️"}[item.get("passed")]
        if item.get("review_only"):
            mark = "🔎"
        title = item.get("title", "")
        explanation = (item.get("explanation") or "").replace("|", "\\|")
        lines.append(f"| {mark} | {title} | {explanation} |")

    # Intent reconciliation, when the smoke baseline produced one.
    adjudication = next(
        (item["adjudication"] for item in ledger.get("evidence", []) if item.get("adjudication")),
        None,
    )
    if adjudication and adjudication.get("deltas"):
        labels = {item["path"]: item for item in adjudication.get("classifications", [])}
        lines += [
            "",
            "<details><summary>Intent reconciliation — every observed difference</summary>",
            "",
            "| Field | Stable | Candidate | Assessment |",
            "|---|---|---|---|",
        ]
        badge = {"explained": "declared", "benign_noise": "non-deterministic", "unexplained": "**UNDECLARED**"}
        for delta in adjudication["deltas"]:
            call = labels.get(delta["path"], {})
            label = call.get("label", "unexplained")
            lines.append(
                f"| `{delta['path']}` | `{delta.get('stable_value')}` | "
                f"`{delta.get('candidate_value')}` | {badge.get(label, label)} — "
                f"{(call.get('rationale') or '').replace('|', chr(92) + '|')} |"
            )
        lines += ["", "</details>"]

    findings = ledger.get("review_findings") or []
    if findings:
        lines += ["", "### 🔎 Generated probes — for review, not blocking", ""]
        lines += [f"- {finding}" for finding in findings]

    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ReleaseProof as a CI release gate.")
    parser.add_argument("--api-url", default=os.getenv("RELEASEPROOF_API_URL"), required=False)
    parser.add_argument("--stable-url", default=os.getenv("RELEASEPROOF_STABLE_URL"))
    parser.add_argument("--candidate-url", default=os.getenv("RELEASEPROOF_CANDIDATE_URL"))
    parser.add_argument("--request-path", default=os.getenv("RELEASEPROOF_REQUEST_PATH", "/"))
    parser.add_argument("--service-name", default=os.getenv("RELEASEPROOF_SERVICE_NAME", "service"))
    parser.add_argument("--summary", default=os.getenv("RELEASEPROOF_SUMMARY"))
    parser.add_argument("--diff", default=os.getenv("RELEASEPROOF_DIFF"))
    parser.add_argument("--diff-base", default=os.getenv("RELEASEPROOF_DIFF_BASE"))
    parser.add_argument("--mode", default=os.getenv("RELEASEPROOF_MODE", "guarded"), choices=["guarded", "explorer"])
    parser.add_argument("--timeout", type=int, default=int(os.getenv("RELEASEPROOF_TIMEOUT", "180")))
    parser.add_argument(
        "--allow-inconclusive",
        action="store_true",
        default=os.getenv("RELEASEPROOF_ALLOW_INCONCLUSIVE", "").lower() == "true",
        help="Exit 0 on INCONCLUSIVE. Off by default: unknown is not the same as safe.",
    )
    args = parser.parse_args()

    missing = [
        name
        for name, value in (
            ("--api-url", args.api_url),
            ("--stable-url", args.stable_url),
            ("--candidate-url", args.candidate_url),
        )
        if not value
    ]
    if missing:
        _annotate("error", f"ReleaseProof gate is missing required inputs: {', '.join(missing)}")
        return EXIT_ERROR

    diff = (args.diff or _default_diff(args.diff_base))[:20000]
    payload = {
        "service_name": args.service_name,
        "summary": args.summary or _default_summary(),
        "diff": diff,
        "stable_url": args.stable_url,
        "candidate_url": args.candidate_url,
        "request_path": args.request_path,
        "analysis_mode": args.mode,
    }

    print(f"ReleaseProof gate -> {args.api_url}")
    print(f"  stable    : {args.stable_url}")
    print(f"  candidate : {args.candidate_url}")
    print(f"  mode      : {args.mode}")
    print(f"  change    : {payload['summary']}")
    print(f"  diff      : {len(diff)} characters")
    print("  running paired probes, this takes up to 90 seconds ...")

    try:
        record = _post(f"{args.api_url.rstrip('/')}/api/analyze", payload, args.timeout)
    except urllib.error.HTTPError as error:
        body = error.read().decode()[:500]
        _annotate("error", f"ReleaseProof API returned {error.code}: {body}")
        return EXIT_ERROR
    except Exception as error:  # network, timeout, malformed response
        _annotate("error", f"ReleaseProof gate could not reach the API: {type(error).__name__}: {error}")
        return EXIT_ERROR

    if record.get("status") == "FAILED":
        _annotate("error", f"ReleaseProof run failed: {record.get('error')}")
        return EXIT_ERROR

    ledger = record.get("ledger") or {}
    verdict = ledger.get("verdict")
    run_id = ledger.get("run_id", "")

    print()
    for item in ledger.get("evidence", []):
        marker = "review" if item.get("review_only") else STATE[item.get("passed")]
        print(f"  [{marker:12}] {item.get('title')}: {item.get('explanation')}")
    print()

    _write_summary(_render(ledger, run_id, args.api_url.rstrip("/")))

    # Generated probes are advisory by construction, so they surface as warnings
    # and never change the exit code.
    for finding in ledger.get("review_findings") or []:
        _annotate("warning", f"ReleaseProof generated-probe finding: {finding}")

    if verdict == "BLOCK":
        for reason in ledger.get("verdict_reasons", []):
            _annotate("error", f"ReleaseProof blocked this release: {reason}")
        print(f"BLOCK — evidence {run_id}")
        return EXIT_BLOCK

    if verdict == "INCONCLUSIVE":
        for reason in ledger.get("verdict_reasons", []):
            _annotate("warning", f"ReleaseProof could not reach a decision: {reason}")
        print(f"INCONCLUSIVE — evidence {run_id}")
        return EXIT_PASS if args.allow_inconclusive else EXIT_INCONCLUSIVE

    print(f"PASS — evidence {run_id}")
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
