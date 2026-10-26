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

# Occupation (SOC) code lists for the underemployment link (step 6).
for y in [2022, 2024]:
    SOURCES.append(("census-codelists", f"SOCP-{y}.json", CENSUS_API.format(y=y, v="SOCP")))

# HC Tables 1-2 (step 7): 2018 weeks intervals, and occupation / industry codes at both ends of 2018-23.
SOURCES.append(("census-codelists", "WKW-2018.json", CENSUS_API.format(y=2018, v="WKW")))
for y in [2018, 2023]:
    for v in ["OCCP", "INDP"]:
        SOURCES.append(("census-codelists", f"{v}-{y}.json", CENSUS_API.format(y=y, v=v)))

# Step 8 (2020-24 5-year file): its user guide and data dictionary, and the 2020 tract -> PUMA
# relationship file (a tract GEOID starts with state + county FIPS) for the South Florida PUMAs.
PUMS_DOCS = "https://www2.census.gov/programs-surveys/acs/tech_docs/pums/"
SOURCES += [
    ("census-5yr", "2020_2024ACS_PUMS_User_Guide.pdf", PUMS_DOCS + "2020_2024ACS_PUMS_User_Guide.pdf"),
    ("census-5yr", "PUMS_Data_Dictionary_2020-2024.csv", PUMS_DOCS + "data_dict/PUMS_Data_Dictionary_2020-2024.csv"),
    ("census-geo", "2020_Census_Tract_to_2020_PUMA.txt",
     "https://www2.census.gov/geo/docs/maps-data/data/rel2020/2020_Census_Tract_to_2020_PUMA.txt"),
]
# Step 9: the 2024 1-year data dictionary, the baseline for the dictionary gate (spec/gates.yaml H8).
SOURCES.append(("census-1yr", "PUMS_Data_Dictionary_2024.csv", PUMS_DOCS + "data_dict/PUMS_Data_Dictionary_2024.csv"))
# The 5-year file codes every year on the 2023 INDP list; these map its codes back to the
# 2017-based codes HC's industry block lists (linked from census.gov industry-occupation code lists).
IO = "https://www2.census.gov/programs-surveys/demo/guidance/industry-occupation/"
for f in ["2022-Census-Industry-Code-List-with-Crosswalk.xlsx",
          "2023-ACS-PUMS-and-2024-SIPP-Public-Use-Industry-Code-List.xlsx"]:
    SOURCES.append(("census-codelists", f, IO + f))

# Census "PUMS estimates for user verification": official estimates + MOEs, the
# fixture for the replicate-weight standard-error test; and the record counts.
EST = "https://www2.census.gov/programs-surveys/acs/tech_docs/pums/estimates/"
for f in ["pums_estimates_24.csv", "pums_record_count_24.csv",
          "pums_estimates_20_24.csv", "pums_record_count_20_24.csv"]:   # 5-year: step 8 fixture
    SOURCES.append(("census-verification", f, EST + f))

# O*NET database releases (text files) for underemployment: the candidates listed in
# spec/rate-grid.yaml (underemployment.onet_release) before any download (2026-10-24).
ONET = "https://www.onetcenter.org/dl_files/database/db_{v}_text.zip"
for v in ["28_0", "28_1", "28_2", "30_0", "30_1", "30_2"]:
    SOURCES.append(("onet", f"db_{v}_text.zip", ONET.format(v=v)))


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
    try:
        wb = wayback(NYFED + "college-labor-outcomes-by-major-data.csv", "20240404203109")  # the snapshot HC fn. 9 cites
    except Exception as e:  # e.g. HTTP 429; the snapshot may already be frozen
        print("WARNING: Wayback lookup failed ->", e)
        wb = None
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
