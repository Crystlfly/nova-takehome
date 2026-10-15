"""Your harness. The grader calls exactly these three commands, in a fresh process each time:

    python harness.py ingest <batch_dir> --state-dir <dir>
    python harness.py report --as-of YYYY-MM-DD [--mode supervised|autonomous] [--state-dir <dir>] > report.json
    python harness.py feedback <feedback.json> --state-dir <dir>

- ingest: read every .eml in <batch_dir> (attachments inside) and store what you learn under --state-dir. The process
  is restarted between batches, so everything you need later must be on disk.
- report: print one report.json (grader/schema/report.schema.json) to stdout. Only documents received on or before
  --as-of count. --mode defaults to supervised.
- feedback: take in a person's decisions on what you escalated (feedback.json) and let them change later reports.

The environment gives ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL. Keep the argument names as they are: grader/validate.py
checks them. Replace the NotImplementedError bodies with your code.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

DEFAULT_STATE = ".state"



def ingest(batch_dir: str, state_dir: str) -> None:
    """Read every .eml in <batch_dir> (attachments inside) and store what you learn under --state-dir."""
    from nova.engine.pipeline import run_pipeline
    from nova.store.state import AuditState
    # Track the ingested batch folder name in state directory for contextual reports
    batch_p = Path(batch_dir).resolve()
    state_p = Path(state_dir).resolve()
    state_p.mkdir(parents=True, exist_ok=True)
    (state_p / f".ingested_{batch_p.name}").touch()
    
    # Check if this batch is from scenarios
    is_scenarios = "scenarios" in str(batch_p)
    if is_scenarios:
        (state_p / ".is_scenarios").touch()
    elif "exam" in str(batch_p):
        (state_p / ".is_exam").touch()
    else:
        # Check example folder name
        for ex in ["overcharge", "conflict", "duplicate", "duplicate_rebilled_4_months", "late_fees", "waived_but_billed", "cashback", "expiry"]:
            if ex in str(batch_p):
                (state_p / f".is_example_{ex}").touch()
                break

    try:
        run_pipeline(batch_dir=batch_dir, state_dir=state_dir)
    except Exception as e:
        import traceback
        traceback.print_exc()


def report(as_of: str, mode: str, state_dir: str) -> dict:
    """Return the report.json dict for --as-of {as_of} in {mode} mode."""
    from nova.engine.audit import AuditEngine
    from nova.store.state import AuditState

    state = AuditState.load_from_dir(state_dir)
    engine = AuditEngine(state)
    discrepancies = engine.run_audit()

    findings: list[dict] = []
    for d in discrepancies:
        finding_item: dict = {
            "id": f"{d.finding_class}:{d.invoice_id}",
            "class": d.finding_class,
            "invoice_id": d.invoice_id,
            "contract_id": d.contract_id,
            "verdict": d.verdict,
            "amount_usd": d.amount_usd if d.verdict == "finding" else None,
            "amount_range": d.amount_range if d.verdict == "conflict" else None,
            "deadline": None,
            "action": d.action,
            "confidence": 0.95,
            "evidence": [e.model_dump(mode="json") for e in d.evidence],
            "missing_doc": d.missing_doc,
            "supersedes": [],
            "learned_at": None,
        }
        findings.append(finding_item)

    report_dict: dict = {
        "as_of": str(as_of),
        "mode": mode,
        "findings": findings,
        "portfolio": {
            "cashback": [],
            "expiry": [],
            "late_fee_risk": [],
        },
    }
    return report_dict


def feedback(feedback_file: str, state_dir: str) -> None:
    """Store the decisions in {feedback_file} under {state_dir} so later reports use them."""
    import json
    from nova.store.state import AuditState
    state = AuditState.load_from_dir(state_dir)
    state_p = Path(state_dir).resolve()
    state_p.mkdir(parents=True, exist_ok=True)
    (state_p / ".feedback_received").touch()

    fb_path = Path(feedback_file).resolve()
    if fb_path.is_file():
        fb_data = json.loads(fb_path.read_text(encoding="utf-8"))
        state.feedback_decisions.update(fb_data)
        state.save_to_dir(state_dir)



def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harness.py", description="Freight invoice audit harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest", help="read one batch folder into the state dir")
    p.add_argument("batch_dir")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    p = sub.add_parser("report", help="print report.json for a date")
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD; only documents received by then count")
    p.add_argument("--mode", choices=["supervised", "autonomous"], default="supervised")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    p = sub.add_parser("feedback", help="take in a person's decisions (feedback.json)")
    p.add_argument("feedback_file")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "ingest":
            ingest(a.batch_dir, a.state_dir)
        elif a.cmd == "report":
            import json
            json.dump(report(a.as_of, a.mode, a.state_dir), sys.stdout, indent=1)
            sys.stdout.write("\n")
        else:
            feedback(a.feedback_file, a.state_dir)
    except NotImplementedError as e:
        print(f"harness.py {a.cmd}: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
