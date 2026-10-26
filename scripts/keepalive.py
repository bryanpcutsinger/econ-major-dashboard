"""Step 11.5 keep-alive (spec/scheduler.yaml workflow_11_5): write data/last-checked.json from one probe run.

    python3 scripts/keepalive.py --probe probe.json --run-url URL [--data data] [--now 2026-10-26T13:17:00Z]

last_success advances only when the probe gave a decision other than error; a missing or unreadable probe output
counts as error. Fingerprints confirmed by a same-sha download ('confirmed') are carried over unchanged.
Standard library only. The page's stale note reads last_success (stale_note_11_4).
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def keepalive(probe_path, run_url, data=ROOT / "data", now=None):
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = read(Path(data) / "last-checked.json") or {}
    probe = read(probe_path) if probe_path else None
    if not isinstance(probe, dict) or "decision" not in probe:
        probe = {"decision": "error", "reasons": [], "errors": ["the probe gave no readable output"]}
    cur = read(Path(data) / "current.json") or {}
    ok = probe["decision"] != "error"
    out = {"last_attempt": now, "last_success": now if ok else old.get("last_success"),
           "decision": probe["decision"], "reasons": probe.get("reasons", [])[:5], "errors": probe.get("errors", [])[:5],
           "live": cur.get("bundle"), "run_url": run_url, "confirmed": old.get("confirmed", {})}
    (Path(data) / "last-checked.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe")
    ap.add_argument("--run-url", default="(local run)")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--now")
    a = ap.parse_args()
    r = keepalive(a.probe, a.run_url, a.data, a.now)
    print(f"{r['decision']}: last_success {r['last_success']}")
