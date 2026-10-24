"""Session-1 pilot: run the pipeline end to end on the Florida 2024 1-year person file.

Checks (each prints PASS or FAIL):
  1. record count equals the Census record-count file
  2. weights + replicate-weight SEs reproduce the Census "estimates for user verification"
  3. every FOD1P code in the file maps to one of the 73 majors (spec/major73.csv)
Then prints, for the NY Fed wage samples: N after each filter, weighted medians
(lower and interpolated; raw and ADJINC dollars) with replicate SEs, and the
unemployment rate for ages 22-27, BA+. Florida is a pipeline test, not a benchmark.

Usage (repo root):  python3 scripts/pilot_florida.py
Output: output/pilot/fl-2024-1yr.json (aggregates only) and its sha256.
"""
import csv
import hashlib
import json
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / "raw" / "acs1-2024" / "csv_pfl.zip"
VER = ROOT / "raw" / "benchmarks" / "census-verification"
OUT = ROOT / "output" / "pilot"
REPS = [f"PWGTP{i}" for i in range(1, 81)]
COLS = ["SERIALNO", "SPORDER", "STATE", "AGEP", "SEX", "RELSHIPP", "SCHL", "SCH", "ESR", "WKHP", "WKWN",
        "WAGP", "PERNP", "COW", "ADJINC", "FOD1P", "FOD2P", "OCCP", "PUMA", "PWGTP"] + REPS


def sdr_se(est, reps):
    """Census successive-difference replication SE: sqrt(4/80 * sum((rep - est)^2))."""
    reps = np.asarray(reps, dtype=float)
    return float(np.sqrt(4.0 / 80.0 * np.sum((reps - est) ** 2)))


def wmedian(values, weights, how):
    """Weighted median. 'lower' = first value where cumulative weight reaches half.
    'interp' = linear interpolation on the weight midpoints (smooths lumpy medians)."""
    order = np.argsort(values, kind="mergesort")  # stable sort: same answer every run
    v, w = np.asarray(values, float)[order], np.asarray(weights, float)[order]
    keep = w > 0
    v, w = v[keep], w[keep]
    cum = np.cumsum(w)
    half = cum[-1] / 2.0
    if how == "lower":
        return float(v[np.searchsorted(cum, half)])
    mid = (cum - w / 2.0) / cum[-1]
    return float(np.interp(0.5, mid, v))


def with_se(fn, df):
    est = fn(df["PWGTP"])
    return est, sdr_se(est, [fn(df[r]) for r in REPS])


def main():
    t0 = time.time()
    checks, result = [], {"source": str(ZIP.relative_to(ROOT)),
                          "zip_sha256": hashlib.sha256(ZIP.read_bytes()).hexdigest()}
    with zipfile.ZipFile(ZIP) as z:
        with z.open("psam_p12.csv") as fh:
            df = pd.read_csv(fh, usecols=COLS, dtype={"SERIALNO": str, "PUMA": str, "OCCP": str,
                                                       "FOD1P": "Int64", "FOD2P": "Int64"})
    df = df.sort_values(["SERIALNO", "SPORDER"], kind="mergesort").reset_index(drop=True)

    # 1. record count
    want = next(int(r["NUMBER_OF_RECORDS"]) for r in csv.DictReader(open(VER / "pums_record_count_24.csv"))
                if r["FILE_NAME"] == "PSAM_P12")
    checks.append(("record count", len(df) == want, f"{len(df):,} vs {want:,}"))

    # 2. verification estimates (person-level rows we can rebuild)
    ver = {r["CHARACTERISTIC"]: (float(r["PUMS_EST_24"]), float(r["PUMS_SE_24"]))
           for r in csv.DictReader(open(VER / "pums_estimates_24.csv")) if r["STATE"] == "12"}
    tests = {"Total population": df.index >= 0, "Total males (SEX=1)": df.SEX == 1,
             "Total females (SEX=2)": df.SEX == 2,
             "GQ institutional population (RELSHIPP=37)": df.RELSHIPP == 37}
    for lo, hi in [(0, 4), (20, 24), (25, 34), (35, 44), (45, 54), (85, 200)]:
        name = f"Age {lo}-{hi}" if hi < 200 else "Age 85 and over"
        tests[name] = df.AGEP.between(lo, hi)
    ver_out = {}
    for name, mask in tests.items():
        sub = df[mask]
        est = float(sub.PWGTP.sum())
        se = sdr_se(est, sub[REPS].sum().values)
        e0, s0 = ver[name]
        ok = abs(est - e0) < 0.5 and abs(se - s0) <= 1.0  # Census rounds SEs to whole people
        checks.append((f"verify {name}", ok, f"est {est:,.0f} vs {e0:,.0f}; SE {se:,.1f} vs {s0:,.0f}"))
        ver_out[name] = {"est": est, "se": se, "census_est": e0, "census_se": s0}
    result["verification"] = ver_out

    # 3. FOD1P coverage
    m73 = {int(r["fod1p"]): r["nyfed_major"] for r in csv.DictReader(open(ROOT / "spec" / "major73.csv"))}
    codes = set(df.FOD1P.dropna().astype(int))
    missing = sorted(codes - set(m73))
    checks.append(("FOD1P codes all mapped", not missing, f"{len(codes)} codes in file; unmapped {missing}"))
    df["major73"] = df.FOD1P.map(lambda c: m73.get(int(c)) if pd.notna(c) else None)

    # NY Fed wage samples: N after each filter (unweighted / weighted)
    steps = [("bachelor's only (SCHL 21)", df.SCHL == 21), ("not enrolled (SCH 1)", df.SCH == 1),
             ("employed (ESR 1,2,4,5)", df.ESR.isin([1, 2, 4, 5])), ("hours >= 35", df.WKHP >= 35),
             ("weeks >= 40", df.WKWN >= 40), ("wage income >= 5,500", df.WAGP >= 5500)]
    result["wages"] = {}
    for label, (lo, hi) in {"early 22-27": (22, 27), "mid 35-45": (35, 45)}.items():
        mask = df.AGEP.between(lo, hi)
        flow = [("ages " + label, int(mask.sum()), float(df.PWGTP[mask].sum()))]
        for name, m in steps:
            mask = mask & m
            flow.append((name, int(mask.sum()), float(df.PWGTP[mask].sum())))
        sample = df[mask]
        out = {"filter_flow": flow}
        for grp_name, grp in [("Overall", sample), ("Economics", sample[sample.major73 == "Economics"])]:
            raw = grp.WAGP.values
            adj = grp.WAGP.values * grp.ADJINC.values / 1e6
            g = {"n": len(grp)}
            for how in ["lower", "interp"]:
                for dol, vals in [("raw", raw), ("adjinc", adj)]:
                    est, se = with_se(lambda w: wmedian(vals, w.values, how), grp)
                    g[f"median_{how}_{dol}"] = {"est": est, "se": se}
            out[grp_name] = g
        result["wages"][label] = out

    # Unemployment, ages 22-27, BA+, not enrolled (one variant from the grid)
    u = df[df.AGEP.between(22, 27) & (df.SCHL >= 21) & (df.SCH == 1) & df.ESR.isin([1, 2, 3, 4, 5])]
    rate = lambda w: 100.0 * w[u.ESR == 3].sum() / w.sum()
    est, se = with_se(rate, u)
    result["unemployment_22_27_ba_plus"] = {"n": len(u), "pct": est, "se_pct": se}

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "fl-2024-1yr.json"
    text = json.dumps(result, indent=1, sort_keys=True)
    path.write_text(text)
    elapsed = time.time() - t0

    for name, ok, info in checks:
        print(("PASS " if ok else "FAIL ") + name + ": " + info)
    for label, out in result["wages"].items():
        print(f"\nWage sample {label}: N after each filter (unweighted / weighted)")
        for name, n, wsum in out["filter_flow"]:
            print(f"  {name:28s} {n:7,d} {wsum:12,.0f}")
        for grp in ["Overall", "Economics"]:
            g = out[grp]
            parts = [f"{k.replace('median_', '')} {v['est']:,.0f} (SE {v['se']:,.0f})"
                     for k, v in g.items() if k != "n"]
            print(f"  {grp} n={g['n']}: " + "; ".join(parts))
    ue = result["unemployment_22_27_ba_plus"]
    print(f"\nUnemployment 22-27 BA+, not enrolled: {ue['pct']:.2f}% (SE {ue['se_pct']:.2f}), n={ue['n']}")
    print(f"\noutput {path.relative_to(ROOT)} sha256 {hashlib.sha256(text.encode()).hexdigest()}")
    print(f"elapsed {elapsed:.1f} s")


if __name__ == "__main__":
    main()
