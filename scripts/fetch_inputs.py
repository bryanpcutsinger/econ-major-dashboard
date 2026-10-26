"""Fetch and verify the build inputs for the current vintage (spec/scheduler.yaml, 11.1).

    python3 scripts/fetch_inputs.py              # non-PUMS inputs: dictionaries, SOCP list, O*NET, tract-to-PUMA
    python3 scripts/fetch_inputs.py --pums       # also the two PUMS zips (~2.9 GB: ask-before)
    python3 scripts/fetch_inputs.py --into DIR   # write under DIR instead of the repo root (tests)
    python3 scripts/fetch_inputs.py --record     # add the current vintage's entries to spec/inputs.json from local files

A file already present with the recorded sha256 is skipped. A download whose sha256 differs from the record is
deleted and the script exits 2 (an upstream change needs a human). An input with no record exits 3: run --record
after a person has accepted the file.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from vintage import V  # noqa: E402

RECORD = ROOT / "spec" / "inputs.json"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def wanted(pums):
    return [p for p in V.urls if pums or p not in V.pums]


def download(url, dest):
    """Stream url to a temp file next to dest; return the temp path (the caller checks it, then renames)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".part-")
    req = urllib.request.Request(url, headers={"User-Agent": "econ-major-dashboard (github.com/bryanpcutsinger)"})
    with os.fdopen(fd, "wb") as out, urllib.request.urlopen(req, timeout=120) as r:
        for b in iter(lambda: r.read(1 << 20), b""):
            out.write(b)
    return Path(tmp)


def fetch(pums=False, into=ROOT):
    rec = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    status = 0
    for p in wanted(pums):
        key = str(p.relative_to(ROOT))
        r = rec.get(key)
        if r is None:
            print(f"NO RECORD  {key}: run --record after a person accepts the file")
            status = max(status, 3)
            continue
        dest = Path(into) / key
        if dest.exists() and sha(dest) == r["sha256"]:
            print(f"ok         {key}")
            continue
        tmp = download(r["url"], dest)
        got = sha(tmp)
        if got != r["sha256"]:
            tmp.unlink()
            print(f"SHA DIFFERS {key}: got {got[:12]}, recorded {r['sha256'][:12]} (upstream changed; nothing kept)")
            status = max(status, 2)
            continue
        tmp.replace(dest)
        print(f"fetched    {key} ({dest.stat().st_size:,} bytes)")
    return status


def record():
    rec = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    for p in wanted(True):
        key = str(p.relative_to(ROOT))
        new = {"url": V.urls[p], "bytes": p.stat().st_size, "sha256": sha(p)}
        old = rec.get(key)
        if old and old["sha256"] != new["sha256"]:
            sys.exit(f"{key}: the local file differs from the record; resolve by hand (never overwrite a record)")
        rec[key] = new
        print(("kept " if old else "added"), key)
    RECORD.write_text(json.dumps(dict(sorted(rec.items())), indent=1) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pums", action="store_true")
    ap.add_argument("--into", default=str(ROOT))
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    if a.record:
        record()
    else:
        sys.exit(fetch(a.pums, a.into))
