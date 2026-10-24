"""Freeze the benchmark files the done checks compare against.

Downloads each source once into raw/benchmarks/<group>/, makes it read-only,
and appends source URL, access time (UTC), size, and SHA-256 to
raw/benchmarks/PROVENANCE.csv. Files that already exist are not re-downloaded.

Run from the repo root:  python3 scripts/freeze_benchmarks.py
Python 3.9 standard library only.
"""
import csv
import datetime as dt
import hashlib
import json
import os
import stat
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "raw" / "benchmarks"
UA = {"User-Agent": "Mozilla/5.0 (econ-major-dashboard benchmark freeze)"}

NYFED = "https://www.newyorkfed.org/medialibrary/research/interactives/data/college-labor-market/"
CENSUS_API = "https://api.census.gov/data/{y}/acs/acs1/pums/variables/{v}.json"

# (group, file name, URL)
SOURCES = [
    ("nyfed-2024", "college-labor-outcomes-by-major-data.csv", NYFED + "college-labor-outcomes-by-major-data.csv"),
    ("nyfed-2024", "college-labor-chart-meta.json", NYFED + "college-labor-chart-meta.json"),
    ("nyfed-2024", "college-labor-market-page.html", "https://www.newyorkfed.org/research/college-labor-market"),
]
# FOD1P (first degree field) value lists, one per single-year vintage HC's tables touch.
# 2020 has no standard 1-year API release, so it is skipped here (UNCERTAIN path).
for y in [2018, 2019, 2021, 2022, 2023, 2024]:
    SOURCES.append(("census-codelists", f"FOD1P-{y}.json", CENSUS_API.format(y=y, v="FOD1P")))

# Definitions of the variables the spec uses (2024 1-year), to check the codes in spec/.
for v in ["ESR", "SCH", "SCHL", "COW", "WKWN", "WKHP", "WAGP", "PERNP", "SEMP", "ADJINC", "AGEP", "FOD2P", "MIL"]:
    SOURCES.append(("census-codelists", f"{v}-2024.json", CENSUS_API.format(y=2024, v=v)))

# Census "PUMS estimates for user verification": official estimates + MOEs, the
# fixture for the replicate-weight standard-error test; and the record counts.
EST = "https://www2.census.gov/programs-surveys/acs/tech_docs/pums/estimates/"
for f in ["pums_estimates_24.csv", "pums_record_count_24.csv"]:
    SOURCES.append(("census-verification", f, EST + f))


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def wayback(url, timestamp):
    """Return the raw-bytes URL of the Wayback snapshot closest to timestamp, or None."""
    q = "https://archive.org/wayback/available?url=" + url + "&timestamp=" + timestamp
    snap = json.loads(fetch(q)).get("archived_snapshots", {}).get("closest")
    if not snap or not snap.get("available"):
        return None
    # The "id_" suffix asks for the original bytes, not the Wayback page wrapper.
    ts = snap["timestamp"]
    return f"https://web.archive.org/web/{ts}id_/{url}", ts


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "PROVENANCE.csv"
    new_log = not log.exists()
    sources = list(SOURCES)
    wb = wayback(NYFED + "college-labor-outcomes-by-major-data.csv", "20240404203109")  # the snapshot HC fn. 9 cites
    if wb:
        url, ts = wb
        sources.append(("nyfed-2022-wayback", f"college-labor-outcomes-by-major-data_wayback-{ts}.csv", url))
    else:
        print("WARNING: no Wayback snapshot found for the April 2024 by-major file")

    with log.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new_log:
            w.writerow(["file", "source_url", "accessed_utc", "bytes", "sha256"])
        for group, name, url in sources:
            path = OUT / group / name
            if path.exists():
                print("exists, skipped:", path.relative_to(ROOT))
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = fetch(url)
            except Exception as e:  # report and keep going; a missing file is visible in the log
                print("FAILED:", url, "->", e)
                continue
            path.write_bytes(data)
            os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # raw is read-only
            sha = hashlib.sha256(data).hexdigest()
            now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            w.writerow([str(path.relative_to(OUT)), url, now, len(data), sha])
            print(f"saved {path.relative_to(ROOT)}  {len(data):,} bytes  {sha[:12]}")


if __name__ == "__main__":
    main()
