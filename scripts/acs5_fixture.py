"""Step 8, done check 1: our weights and SE code reproduce Census's 2020-24 verification estimates.

Compares the state sums written by scripts/extract_acs5.py (all person records) with every person
row of pums_estimates_20_24.csv, and the record counts per CSV part with pums_record_count_20_24.csv.
Pass (spec/acs5-panels.yaml fixture): estimate exact; SE within 1 (Census rounds SEs to whole people).

Run from the repo root:  python3 scripts/acs5_fixture.py
"""
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VER = ROOT / "raw" / "benchmarks" / "census-verification"
CHK = ROOT / "output" / "checks"


def main():
    sums = {}
    for r in csv.DictReader(open(CHK / "acs5-fixture-sums.csv")):
        w = np.array([float(r["PWGTP"])] + [float(r[f"PWGTP{i}"]) for i in range(1, 81)])
        sums[(r["STATE"], r["CHARACTERISTIC"])] = w
        us = ("US", r["CHARACTERISTIC"])                 # national row = sum of the state sums
        sums[us] = sums.get(us, 0) + w
    ours = {k: (w[0], np.sqrt(4 / 80 * ((w[1:] - w[0]) ** 2).sum())) for k, w in sums.items()}
    names = {c for _, c in ours}
    pub = [r for r in csv.DictReader(open(VER / "pums_estimates_20_24.csv"))
           if r["CHARACTERISTIC"] in names and r["STATE"] != "72"]   # Puerto Rico is not in the national files
    n_ok, misses = 0, []
    for r in pub:
        key = (r["STATE"], r["CHARACTERISTIC"])
        est, se = ours.get(key, (np.nan, np.nan))
        ok = abs(est - float(r["PUMS_EST_20_TO_24"])) < 0.5 and abs(se - float(r["PUMS_SE_20_TO_24"])) <= 1.0
        n_ok += ok
        if not ok:
            misses.append(f"{key}: est {est:,.0f} vs {r['PUMS_EST_20_TO_24']}; SE {se:,.1f} vs {r['PUMS_SE_20_TO_24']}")
    states = len({r["STATE"] for r in pub})
    print(f"verification rows: {n_ok}/{len(pub)} pass ({states - 1} states + US x {len(names)} person rows)")
    for m in misses[:20]:
        print("  miss:", m)

    counts = json.loads((CHK / "acs5-profile.json").read_text())["records_by_file"]
    want = {r["FILE_NAME"].lower(): int(r["NUMBER_OF_RECORDS"])
            for r in csv.DictReader(open(VER / "pums_record_count_20_24.csv")) if r["FILE_TYPE"] == "Person"}
    rec_ok = True
    for name, n in sorted(counts.items()):
        w = want.get(name.replace(".csv", ""))
        rec_ok &= n == w
        print(f"  records {name}: {n:,} vs Census {w:,}" if w else f"  records {name}: {n:,} (no Census row)")
    passed = n_ok == len(pub) and len(pub) > 0 and rec_ok
    print(f"\nfixture: {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    main()
