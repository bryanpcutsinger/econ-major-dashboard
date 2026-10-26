"""Done check 2, HC Table 3: frequency, share, median earnings, and self-employment by major (2021-23).

Rules pre-registered in ledger E28 (with E22) before this script ran. First an exact pin: the
econ counts by year that HC print in their code comments. Then all 73 rows of Table 3.

Run from the repo root:  python3 scripts/hc_table3_check.py
Reads raw/acs1-{2021,2022,2023}/csv_pus.zip (read-only); writes output/checks/hc-table3.csv.
Pass (D1): frequency exact; share +-0.05 pt; median within $0.50 = exact, pass = >= 90% exact
and all within 1%; self-employment +-0.1 pt.
"""
import csv
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from extract_hc_major_map import SPELLING  # noqa: E402  (HC spelling -> NY Fed spelling)

YEARS = [2021, 2022, 2023]
CPI99 = {2021: 0.615, 2022: 0.569, 2023: 0.547}       # IPUMS page, frozen in raw/benchmarks/ipums/
ECON = {5501, 6205, 1102}
COLS = ["SERIALNO", "SPORDER", "AGEP", "SCHL", "SCH", "ESR", "WKHP", "WKWN", "PERNP", "COW", "FOD1P", "PWGTP"]
# HC code comments (R lines 92-109): econ rows by year under subset1a, unweighted and PERWT-weighted
HC_ECON = {2021: (1489, 159730), 2022: (1603, 169051), 2023: (1726, 185019)}


def load(year):
    """Ages 35-45 with a bachelor's as the highest degree, one survey year."""
    z = zipfile.ZipFile(ROOT / "raw" / f"acs1-{year}" / "csv_pus.zip")
    parts = []
    for name in sorted(n for n in z.namelist() if n.startswith("psam_pus") and n.endswith(".csv")):
        with z.open(name) as fh:
            for chunk in pd.read_csv(fh, usecols=COLS, chunksize=500_000,
                                     dtype={"SERIALNO": str, "FOD1P": "Int64"}):
                parts.append(chunk[chunk.AGEP.between(35, 45) & (chunk.SCHL == 21)])
    df = pd.concat(parts, ignore_index=True).sort_values(["SERIALNO", "SPORDER"], kind="mergesort")
    df["YEAR"] = year
    print(f"  read {year}: {len(df):,} persons aged 35-45, bachelor's only", flush=True)
    return df


def weighted_median(x, w, type_):
    """spatstat.univar weighted.quantile at 0.5, types 1, 2, 4 (frozen source, R/weightedStats.R)."""
    o = np.argsort(x, kind="mergesort")
    x, w = x[o], w[o]
    Fx = np.cumsum(w) / w.sum()
    if type_ == 1:                            # first x with F(x) >= 0.5
        return x[min(np.searchsorted(Fx, 0.5, side="left"), len(x) - 1)]
    if type_ == 4:                            # linear interpolation of the CDF
        return float(np.interp(0.5, Fx, x))
    j = max(np.searchsorted(Fx, 0.5, side="right") - 1, 0)   # last index with F <= 0.5 (or the first)
    g = 0.5 - Fx[j]
    if g < 0:
        return x[j]
    return (x[j] + x[min(j + 1, len(x) - 1)]) / 2 if g == 0 else x[min(j + 1, len(x) - 1)]


def main():
    t0 = time.time()
    df = pd.concat([load(y) for y in YEARS], ignore_index=True)
    core = ((df.SCH == 1) & df.ESR.isin([1, 2, 4, 5]) & (df.WKHP >= 35) & (df.WKWN >= 40)).to_numpy()
    df["INCEARNadj"] = df.PERNP * df.YEAR.map(CPI99) * 1.797    # HC line 71, same order

    # Exact pin first: HC's per-year econ counts (subset1a: nominal earnings > 5499)
    print("\nPin: HC econ counts by year (unweighted / weighted), ours vs HC code comments")
    a = core & (df.PERNP > 5499).to_numpy() & df.FOD1P.isin(ECON).to_numpy()
    pin_ok = True
    for y in YEARS:
        s = a & (df.YEAR == y).to_numpy()
        ours = (int(s.sum()), int(df.PWGTP[s].sum()))
        pin_ok &= ours == HC_ECON[y]
        print(f"  {y}: ours {ours}  HC {HC_ECON[y]}  {'EXACT' if ours == HC_ECON[y] else 'MISS'}")

    # Table 3 sample (subset1c3) and the 73-group map
    m73 = {int(r["fod1p"]): r["nyfed_major"] for r in csv.DictReader(open(ROOT / "raw/benchmarks/hc-2026-openicpsr/derived/major73-hc.csv"))
           if r["nyfed_major"]}
    s = df[core & (df.INCEARNadj > 5499).to_numpy()].copy()
    s["g"] = s.FOD1P.map(lambda c: m73.get(int(c)) if pd.notna(c) else None)
    unlisted = s[s.g.isna()]
    print(f"\nTable 3 sample: {len(s):,} persons; FOD1P codes outside the recode: {len(unlisted)} "
          f"({sorted(unlisted.FOD1P.dropna().unique().tolist())})")
    total = len(s)

    pub = list(csv.DictReader(open(ROOT / "raw" / "benchmarks" / "hc-2026" / "table3.csv")))
    to_nyfed = {k.lower(): v for k, v in SPELLING.items()}
    lower_names = {v.lower(): v for v in m73.values()}
    rows, no_selfemp = [], []
    for p in pub:
        name = to_nyfed.get(p["major"].lower(), lower_names.get(p["major"].lower()))
        g = s[s.g == name]
        x, w = g.INCEARNadj.to_numpy(float), g.PWGTP.to_numpy(float)
        freq = len(g)
        n_self = int(g.COW.isin([6, 7]).sum())
        if n_self == 0:
            no_selfemp.append(p["major"])
        med = {t: float(weighted_median(x, w, t)) for t in (1, 2, 4)}
        share, selfemp = 100 * freq / total, 100 * n_self / freq
        rows.append(dict(
            major=p["major"], freq_pub=int(p["frequency"]), freq=freq,
            share_pub=float(p["pct_of_sample"]), share=round(share, 4),
            median_pub=int(p["median_income"]), median_t2=round(med[2], 2),
            median_t1=round(med[1], 2), median_t4=round(med[4], 2),
            selfemp_pub=float(p["self_employment_rate"]), selfemp=round(selfemp, 4),
            freq_ok=freq == int(p["frequency"]),
            share_ok=abs(share - float(p["pct_of_sample"])) <= 0.05 + 1e-9,
            median_exact=abs(med[2] - int(p["median_income"])) <= 0.5,
            median_within_1pct=abs(med[2] / int(p["median_income"]) - 1) <= 0.01,
            selfemp_ok=abs(selfemp - float(p["self_employment_rate"])) <= 0.1 + 1e-9))

    out = ROOT / "output" / "checks" / "hc-table3.csv"
    with out.open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)

    n = len(rows)
    count = lambda k: sum(r[k] for r in rows)
    exact = {t: sum(abs(r[f"median_t{t}"] - r["median_pub"]) <= 0.5 for r in rows) for t in (1, 2, 4)}
    print(f"\nTotal: ours {total:,} vs HC 224,415 {'EXACT' if total == 224415 else 'MISS'}")
    print(f"Majors without a self-employed person (cbind would misalign): {no_selfemp or 'none'}")
    print(f"Frequency exact:            {count('freq_ok')}/{n}")
    print(f"Share within 0.05 pt:       {count('share_ok')}/{n}")
    print(f"Median (type 2) exact:      {exact[2]}/{n}; within 1%: {count('median_within_1pct')}/{n}"
          f"   [diagnostic: type 1 exact {exact[1]}, type 4 exact {exact[4]}]")
    print(f"Self-employment within 0.1: {count('selfemp_ok')}/{n}")
    passed = (pin_ok and total == 224415 and count("freq_ok") == n and count("share_ok") == n
              and exact[2] >= 0.9 * n and count("median_within_1pct") == n and count("selfemp_ok") == n)
    print(f"\nTable 3 done check: {'PASS' if passed else 'FAIL'}; wrote {out.relative_to(ROOT)}; "
          f"elapsed {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
