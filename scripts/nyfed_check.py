"""Done check 1, wages: reproduce the NY Fed by-major median wages from Census PUMS.

Runs every wage variant declared in spec/rate-grid.yaml (no others), compares
all 73 majors + Overall against the frozen NY Fed file for that year, and logs
every variant to output/checks/nyfed-wages-<year>.csv. Point estimates only:
standard errors are not needed to match a benchmark.

Usage (repo root):
  python3 scripts/nyfed_check.py 2024    # vs raw/benchmarks/nyfed-2024 (ACS 2024)
  python3 scripts/nyfed_check.py 2022    # vs the Feb 2024 posting HC matched (ACS 2022)
  python3 scripts/nyfed_check.py 2022 spec/major73-hc.csv   # another major map; outputs get "-<map stem>"

Match rule: the NY Fed rounds medians (to $100 or $1,000), so |ours - theirs| <= $50
counts as exact. Tolerance (spec D1): Overall exact; every miss <= 2% and reconciled.
"""
import csv
import gzip
import io
import itertools
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COLS = ["SERIALNO", "SPORDER", "AGEP", "SCHL", "SCH", "ESR", "WKHP", "WKWN", "WAGP",
        "ADJINC", "FOD1P", "FOD2P", "PWGTP"]
GRID = {  # spec/rate-grid.yaml, nyfed_wages (+ the dollar rule from benchmarks.yaml)
    "weeks": [">=40", ">40"],
    "armed_forces": ["included", "excluded"],
    "threshold_dollars": ["nominal", "adjinc"],
    "median": ["lower", "interp"],
    "major_field": ["first", "either"],
    "dollars": ["raw", "adjinc"],
}
AGES = {"early": (22, 27), "mid": (35, 45)}


def load(year):
    """Persons aged 22-45 with exactly a bachelor's degree, from every national person file."""
    z = zipfile.ZipFile(ROOT / "raw" / f"acs1-{year}" / "csv_pus.zip")
    parts = []
    for name in sorted(n for n in z.namelist() if n.startswith("psam_pus") and n.endswith(".csv")):
        with z.open(name) as fh:
            for chunk in pd.read_csv(fh, usecols=COLS, chunksize=500_000,
                                     dtype={"SERIALNO": str, "FOD1P": "Int64", "FOD2P": "Int64"}):
                parts.append(chunk[(chunk.AGEP.between(22, 45)) & (chunk.SCHL == 21)])
        print(f"  read {name}", flush=True)
    df = pd.concat(parts, ignore_index=True)
    return df.sort_values(["SERIALNO", "SPORDER"], kind="mergesort").reset_index(drop=True)


def benchmark(year):
    if year == 2024:
        text = (ROOT / "raw/benchmarks/nyfed-2024/college-labor-outcomes-by-major-data.csv").read_text()
    else:
        f = next((ROOT / "raw/benchmarks/nyfed-2022-wayback").glob("college-labor-outcomes-by-major-data_*.csv"))
        raw = f.read_bytes()
        text = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text.replace("\r\n", "\n").replace("\r", "\n"))))
    return {r["Major"]: (float(r["Median Wage Early Career"]), float(r["Median Wage Mid-Career"])) for r in rows}


def wmedian_by_group(values, weights, groups, how):
    """Weighted median of `values` within each group (lower or interpolated)."""
    d = pd.DataFrame({"v": values, "w": weights, "g": groups})
    d = d[d.w > 0].sort_values(["g", "v"], kind="mergesort")
    out = {}
    for g, sub in d.groupby("g", sort=True):
        v, w = sub.v.to_numpy(float), sub.w.to_numpy(float)
        cum = np.cumsum(w)
        if how == "lower":
            out[g] = float(v[np.searchsorted(cum, cum[-1] / 2.0)])
        else:
            out[g] = float(np.interp(0.5, (cum - w / 2.0) / cum[-1], v))
    return out


def main(year, map_path="spec/major73.csv"):
    t0 = time.time()
    bench = benchmark(year)
    m73 = {int(r["fod1p"]): r["nyfed_major"] for r in csv.DictReader(open(ROOT / map_path)) if r["nyfed_major"]}
    tag = "" if Path(map_path).stem == "major73" else "-" + Path(map_path).stem
    print(f"loading ACS {year} 1-year ...", flush=True)
    df = load(year)
    df["g1"] = df.FOD1P.map(lambda c: m73.get(int(c)) if pd.notna(c) else None)
    df["g2"] = df.FOD2P.map(lambda c: m73.get(int(c)) if pd.notna(c) else None)
    unmapped = sorted(set(df.FOD1P.dropna().astype(int)) - set(m73))
    print(f"  {len(df):,} persons aged 22-45 with a BA only; unmapped FOD1P codes: {unmapped}")

    log_rows, best = [], None
    keys = list(GRID)
    for combo in itertools.product(*GRID.values()):
        v = dict(zip(keys, combo))
        adj = df.ADJINC.to_numpy(float) / 1e6
        wage = df.WAGP.to_numpy(float) * (adj if v["dollars"] == "adjinc" else 1.0)
        thresh_wage = df.WAGP.to_numpy(float) * (adj if v["threshold_dollars"] == "adjinc" else 1.0)
        employed = [1, 2, 4, 5] if v["armed_forces"] == "included" else [1, 2]
        weeks_ok = df.WKWN >= 40 if v["weeks"] == ">=40" else df.WKWN > 40
        base = (df.SCH == 1) & df.ESR.isin(employed) & (df.WKHP >= 35) & weeks_ok & (thresh_wage >= 5500)
        result = {}
        for age, (lo, hi) in AGES.items():
            m = (base & df.AGEP.between(lo, hi)).to_numpy()
            vals, wts = wage[m], df.PWGTP.to_numpy(float)[m]
            g = df.g1.to_numpy(object)[m]
            if v["major_field"] == "either":  # a double major counts in both groups
                g2 = df.g2.to_numpy(object)[m]
                extra = pd.notna(g2) & (g2 != g)
                vals, wts, g = (np.concatenate([vals, vals[extra]]), np.concatenate([wts, wts[extra]]),
                                np.concatenate([g, g2[extra]]))
            med = wmedian_by_group(vals, wts, g, v["median"])
            med["Overall"] = wmedian_by_group(wage[m], df.PWGTP.to_numpy(float)[m],
                                              np.zeros(m.sum()), v["median"])[0.0]
            result[age] = med
        cells, exact, worst = 0, 0, 0.0
        for major, (e_b, m_b) in bench.items():
            for age, b in [("early", e_b), ("mid", m_b)]:
                ours = result[age].get(major, np.nan)
                gap = abs(ours - b)
                cells += 1
                exact += gap <= 50
                worst = max(worst, gap / b)
        overall_ok = all(abs(result[a]["Overall"] - bench["Overall"][i]) <= 50 for i, a in enumerate(AGES))
        row = dict(v, exact_cells=exact, cells=cells, worst_pct=round(100 * worst, 2), overall_exact=overall_ok)
        log_rows.append(row)
        if best is None or (exact, -worst) > (best[0]["exact_cells"], -best[0]["worst_pct"]):
            best = (row, result)

    out = ROOT / "output" / "checks"
    out.mkdir(parents=True, exist_ok=True)
    with (out / f"nyfed-wages-{year}{tag}.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(log_rows[0]))
        w.writeheader()
        w.writerows(sorted(log_rows, key=lambda r: (-r["exact_cells"], r["worst_pct"])))
    row, result = best
    with (out / f"nyfed-wages-{year}{tag}-best-cells.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["major", "age", "nyfed", "ours", "gap", "gap_pct"])
        for major, (e_b, m_b) in bench.items():
            for age, b in [("early", e_b), ("mid", m_b)]:
                ours = result[age].get(major, np.nan)
                w.writerow([major, age, b, round(ours, 2), round(ours - b, 2), round(100 * (ours - b) / b, 2)])

    print("\nTop variants (exact cells of 148, worst miss %):")
    for r in sorted(log_rows, key=lambda r: (-r["exact_cells"], r["worst_pct"]))[:8]:
        print("  ", {k: r[k] for k in keys}, r["exact_cells"], r["worst_pct"], "overall exact" if r["overall_exact"] else "")
    print(f"\n{len(log_rows)} variants logged to output/checks/nyfed-wages-{year}{tag}.csv; elapsed {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main(int(sys.argv[1]), *sys.argv[2:3])
