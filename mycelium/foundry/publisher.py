"""Fail-soft JSONL writer. Never blocks the caller, never raises.

The publisher is the hot path — it must survive disk-full, permission errors,
encoding issues, or any other surprise without taking down the agent that's
trying to log a decision.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()
_log_dir_override: Path | None = None


def set_log_dir(path: str | Path) -> None:
    """Pin the log directory at runtime (called by server.set_config)."""
    global _log_dir_override
    _log_dir_override = Path(os.path.expandvars(str(path))).expanduser()


def _resolve_log_dir() -> Path:
    """Where to write today's JSONL. Order: explicit override > env var > default."""
    if _log_dir_override is not None:
        path = _log_dir_override
    else:
        raw = os.environ.get("MYCELIUM_FOUNDRY_LOG_DIR") or "~/.mycelium/foundry/logs"
        path = Path(os.path.expandvars(raw)).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _log_path() -> Path:
    return _resolve_log_dir() / f"decisions-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"


def publish(
    decision_point: str,
    agent: str,
    decision_made,
    *,
    input_features: dict | None = None,
    alternatives_considered=None,
    outcome=None,
    elapsed_ms: int | None = None,
    cost: float | None = None,
    qc_status: str | None = None,
    failure_class: str | None = None,
    failure_detail: str | None = None,
    trap_pattern_ref: str | None = None,
    tier: str | None = None,
    client_id: str | None = None,
    trace_id: str | None = None,
    source_file: str | None = None,
    source_line: int | None = None,
    ts: datetime | str | None = None,
) -> bool:
    """Append one decision row to today's JSONL.

    Returns True on success, False on any failure (silent — caller is not blocked).
    """
    try:
        if ts is None:
            ts_str = datetime.now(timezone.utc).isoformat()
        elif isinstance(ts, datetime):
            ts_str = ts.isoformat()
        else:
            ts_str = str(ts)
        row = {
            "ts": ts_str,
            "decision_point": decision_point,
            "agent": agent,
            "decision_made": "" if decision_made is None else str(decision_made),
            "input_features": input_features or {},
            "alternatives_considered": alternatives_considered,
            "outcome": outcome,
            "elapsed_ms": elapsed_ms,
            "cost": cost,
            "qc_status": qc_status,
            "failure_class": failure_class,
            "failure_detail": failure_detail,
            "trap_pattern_ref": trap_pattern_ref,
            "tier": tier,
            "client_id": client_id,
            "trace_id": trace_id,
            "source_file": source_file,
            "source_line": source_line,
        }
        line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
        with _lock:
            with _log_path().open("a", encoding="utf-8") as f:
                f.write(line)
        return True
    except Exception:
        return False
