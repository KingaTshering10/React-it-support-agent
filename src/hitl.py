"""Serialized console approval and a local append-only JSONL event log."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

AUDIT_LOG_PATH = Path(__file__).resolve().parents[1] / "logs/audit_log.jsonl"
_AUDIT_LOCK = Lock()
_APPROVAL_LOCK = Lock()


def _write_audit_entry(entry):
    record = {**entry, "timestamp": datetime.now(timezone.utc).isoformat()}
    with _AUDIT_LOCK:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_tool_call(tool_name, tool_input, result_summary):
    _write_audit_entry({"event": "tool_call", "tool": tool_name,
                        "input": tool_input, "result_summary": result_summary})


def request_approval(action_description, details):
    """Approve only an explicit yes or mock automation setting; EOF/cancel deny."""
    with _APPROVAL_LOCK:
        auto = os.getenv("HITL_AUTO_DECISION", "").strip().lower()
        print("\nHUMAN APPROVAL REQUIRED · simulated state change")
        print("Action:", action_description)
        for key, value in details.items():
            print(f"  {key}: {value}")
        mode = "interactive"
        if auto in {"approve", "deny"}:
            approved = auto == "approve"
            mode = "auto"
            print(f"Mock automation setting: {auto}")
        else:
            try:
                answer = input("Approve this action? [y/N]: ").strip().lower()
                approved = answer in {"y", "yes"}
            except (EOFError, KeyboardInterrupt):
                approved = False
                mode = "interrupted"
                print("\nApproval input unavailable or cancelled; action denied.")
        # An approval-log failure propagates before a restart can execute.
        _write_audit_entry({"event": "hitl_decision", "action": action_description,
                            "details": details, "approved": approved, "mode": mode})
        print("APPROVED\n" if approved else "DENIED\n")
        return approved
