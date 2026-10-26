"""Done check 1, rates: calibrate NY Fed unemployment and graduate-degree share by major.

Calibration, not replication: no published code covers the rates (HC code = wages only).
Runs the variants declared in spec/rate-grid.yaml (nyfed_rates) and logs every one to
output/checks/nyfed-rates-<year>.csv. Majors use raw/benchmarks/hc-2026-openicpsr/derived/major73-hc.csv (ledger E17).

  unemployment: ages 22-27, SCHL >= 21, not enrolled (SCH == 1); unemployed (ESR 3) / labor force
  graduate share: ages 25-65, SCHL 22-24 among SCHL >= 21

Grid notes (fixed before any rate result was seen):
- For unemployment, `armed_forces` and `unemployment_denominator` both decide one thing:
  whether ESR 4-5 enter the labor force. They give two distinct results, run as
  "civilian" (ESR 1-3) and "with_armed" (ESR 1-5).
- For graduate share, `graduate_share_population` = all vs SCH == 1, and `armed_forces` =
  included vs excluded (ESR 4-5 dropped from the population; run added 2026-10-24, ledger E24).
- `major_field` = first vs either (a double major counts in both groups).

Usage (repo root):
  python3 scripts/nyfed_rates_check.py 2024    # vs raw/benchmarks/nyfed-2024
  python3 scripts/nyfed_rates_check.py 2022    # vs the Feb 2024 posting (ACS 2022)

Tolerance (spec D1): Overall +-0.01 pt; each major +-0.05 pt; escalate beyond +-0.25 pt.
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
COLS = ["SERIALNO", "SPORDER", "AGEP", "SCHL", "SCH", "ESR", "FOD1P", "FOD2P", "PWGTP"]
LABOR_FORCE = {"civilian": [1, 2, 3], "with_armed": [1, 2, 3, 4, 5]}
MEASURES = {"unemployment": "Unemployment Rate", "grad_share": "Share with Graduate Degree"}


def load(year):
    """Persons aged 22-65 with a bachelor's degree or more, from every national person file."""
    z = zipfile.ZipFile(ROOT / "raw" / f"acs1-{year}" / "csv_pus.zip")
    parts = []
    for name in sorted(n for n in z.namelist() if n.startswith("psam_pus") and n.endswith(".csv")):
        with z.open(name) as fh:
            for chunk in pd.read_csv(fh, usecols=COLS, chunksize=500_000,
                                     dtype={"SERIALNO": str, "FOD1P": "Int64", "FOD2P": "Int64"}):
                parts.append(chunk[(chunk.AGEP.between(22, 65)) & (chunk.SCHL >= 21)])
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
    return {r["Major"]: {m: float(r[col]) for m, col in MEASURES.items()} for r in rows}


def group_rates(num, den, w, g1, g2, either):
    """100 * sum(w * num) / sum(w * den) within each major group, plus Overall (each person once)."""
    d = pd.DataFrame({"n": num * w, "d": den * w, "g": g1})
    if either:  # a double major counts in both groups
        extra = pd.notna(g2) & (g2 != g1)
        d = pd.concat([d, pd.DataFrame({"n": (num * w)[extra], "d": (den * w)[extra], "g": g2[extra]})])
    s = d.dropna(subset=["g"]).groupby("g")[["n", "d"]].sum()
    out = (100 * s.n / s.d).to_dict()
    out["Overall"] = 100 * float((num * w).sum() / (den * w).sum())
    return out


def score(ours, bench, measure):
    cells, ok, worst, overall_gap = 0, 0, 0.0, None
    for major, b in bench.items():
        gap = abs(ours.get(major, np.nan) - b[measure])
        if major == "Overall":
            overall_gap = gap
            continue
        cells += 1
        ok += gap <= 0.05
        worst = max(worst, gap)
    return dict(within_005=ok, cells=cells, worst_pt=round(worst, 3), overall_gap_pt=round(overall_gap, 4))


def main(year):
    t0 = time.time()
    bench = benchmark(year)
    m73 = {int(r["fod1p"]): r["nyfed_major"] for r in csv.DictReader(open(ROOT / "raw/benchmarks/hc-2026-openicpsr/derived/major73-hc.csv"))
           if r["nyfed_major"]}
    print(f"loading ACS {year} 1-year ...", flush=True)
    df = load(year)
    g1 = df.FOD1P.map(lambda c: m73.get(int(c)) if pd.notna(c) else None).to_numpy(object)
    g2 = df.FOD2P.map(lambda c: m73.get(int(c)) if pd.notna(c) else None).to_numpy(object)
    w = df.PWGTP.to_numpy(float)
    print(f"  {len(df):,} persons aged 22-65 with a BA or more; no major group: {int(pd.isna(g1).sum())}")

    rows, best = [], {}
    young = (df.AGEP.between(22, 27) & (df.SCH == 1)).to_numpy()
    for lf, field in itertools.product(LABOR_FORCE, ["first", "either"]):
        den = (young & df.ESR.isin(LABOR_FORCE[lf]).to_numpy()).astype(float)
        num = (young & (df.ESR == 3).to_numpy()).astype(float)
        ours = group_rates(num, den, w, g1, g2, field == "either")
        rows.append(dict(measure="unemployment", labor_force=lf, grad_population="", major_field=field,
                         **score(ours, bench, "unemployment")))
        best.setdefault("unemployment", []).append((rows[-1], ours))
    adult = df.AGEP.between(25, 65).to_numpy()
    for pop, field, armed in itertools.product(["all", "not_enrolled"], ["first", "either"], ["included", "excluded"]):
        base = adult & ((df.SCH == 1).to_numpy() if pop == "not_enrolled" else True)
        base = base & (~df.ESR.isin([4, 5]).to_numpy() if armed == "excluded" else True)
        num = (base & df.SCHL.between(22, 24).to_numpy()).astype(float)
        ours = group_rates(num, base.astype(float), w, g1, g2, field == "either")
        rows.append(dict(measure="grad_share", labor_force=f"armed_{armed}", grad_population=pop, major_field=field,
                         **score(ours, bench, "grad_share")))
        best.setdefault("grad_share", []).append((rows[-1], ours))

    out = ROOT / "output" / "checks"
    out.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["measure"], -r["within_005"], r["worst_pt"]))
    with (out / f"nyfed-rates-{year}.csv").open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    with (out / f"nyfed-rates-{year}-best-cells.csv").open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["measure", "major", "nyfed", "ours", "gap_pt"])
        for measure, cands in best.items():
            row, ours = max(cands, key=lambda c: (c[0]["within_005"], -c[0]["worst_pt"]))
            for major, b in bench.items():
                o = ours.get(major, np.nan)
                wr.writerow([measure, major, b[measure], round(o, 3), round(o - b[measure], 3)])

    print("\nVariants (majors within +-0.05 pt of 73; worst gap; Overall gap):")
    for r in rows:
        print("  ", r)
    print(f"\n{len(rows)} variants logged to output/checks/nyfed-rates-{year}.csv; elapsed {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main(int(sys.argv[1]))
