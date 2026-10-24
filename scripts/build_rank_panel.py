"""Build the rank panel: where each of the 73 majors ranks on four measures, with uncertainty.

Spec: spec/rank-panel.yaml (written before any result; two instructor rulings after the first
build). For each measure and switch setting: the estimate, its SDR standard error from
PWGTP1-80, the unweighted n, the hide flag (D5 for pay, a count rule for rates), and the
point rank (the page shows this). Audit only: a 90% rank range from pairwise tests and the
number of majors "about the same".

Run from the repo root:  python3 scripts/build_rank_panel.py
Reads raw/ (read-only); writes output/panels/rank-2024.{json,csv}.
"""
import csv
import itertools
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from nyfed_underemployment_check import onet_scores, soc6_scores, socp_flags  # noqa: E402  (one job rule)

YEAR = 2024
REPS = [f"PWGTP{r}" for r in range(1, 81)]
WCOLS = ["PWGTP"] + REPS                      # column 0 = full-sample weight
COLS = ["SERIALNO", "SPORDER", "AGEP", "SCHL", "SCH", "ESR", "WKHP", "WKWN", "WAGP", "ADJINC",
        "FOD1P", "SOCP"] + WCOLS
Z90 = 1.645
ONET_RELEASE, LINK = "30_2", "8digit_mean"    # E27 production default


def load():
    z = zipfile.ZipFile(ROOT / "raw" / f"acs1-{YEAR}" / "csv_pus.zip")
    parts = []
    for name in sorted(n for n in z.namelist() if n.startswith("psam_pus") and n.endswith(".csv")):
        with z.open(name) as fh:
            for chunk in pd.read_csv(fh, usecols=COLS, chunksize=500_000,
                                     dtype={"SERIALNO": str, "SOCP": str, "FOD1P": "Int64"}):
                parts.append(chunk[chunk.AGEP.between(22, 45) & (chunk.SCHL >= 21)])
        print(f"  read {name}", flush=True)
    df = pd.concat(parts, ignore_index=True)
    return df.sort_values(["SERIALNO", "SPORDER"], kind="mergesort").reset_index(drop=True)


def medians(v, W):
    """Lower and interpolated weighted medians of v for every weight column of W (n x 81)."""
    o = np.argsort(v, kind="mergesort")
    v, W = v[o], W[o]
    cum = np.cumsum(W, axis=0)
    tot = cum[-1]
    lower = v[(cum >= tot / 2).argmax(axis=0)]
    mid = (cum - W / 2) / tot
    interp = np.array([np.interp(0.5, mid[:, r], v) for r in range(W.shape[1])])
    return lower, interp


def summarize(majors, test, shown, n, better, n_num=None):
    """Ranks, ranges, and flags from a (73 x 81) test-statistic matrix and the shown estimates.

    n_num (rates only) = unweighted people in the numerator; rates use the count hide rule.
    """
    se = np.sqrt(4 / 80 * ((test[:, 1:] - test[:, [0]]) ** 2).sum(axis=1))
    d = test[:, None, :] - test[None, :, :]                       # i minus j, every weight column
    se_d = np.sqrt(4 / 80 * ((d[..., 1:] - d[..., [0]]) ** 2).sum(axis=-1))
    sign = 1 if better == "higher" else -1
    sig = np.abs(d[..., 0]) > Z90 * se_d
    sig_better = sig & (sign * d[..., 0] < 0)                     # [i, j]: j significantly better than i
    sig_worse = sig & (sign * d[..., 0] > 0)
    rows = []
    for i, m in enumerate(majors):
        est = shown[i]
        moe_ratio = Z90 * se[i] / est if est > 0 else np.inf
        lo = 1 + int(sig_better[i].sum())
        hi = len(majors) - int(sig_worse[i].sum())
        rows.append(dict(
            major=m, estimate=round(float(est), 3), se=round(float(se[i]), 3), n=int(n[i]),
            moe_ratio=round(float(moe_ratio), 3),
            hidden=bool(n[i] < 100 or (moe_ratio > 0.30 if n_num is None else min(n_num[i], n[i] - n_num[i]) < 10)),
            rank=1 + int((sign * (shown - est) > 0).sum()), rank_lo=lo, rank_hi=hi,
            n_about_same=len(majors) - 1 - int(sig_better[i].sum()) - int(sig_worse[i].sum())))
    return rows


def main():
    t0 = time.time()
    m73 = {int(r["fod1p"]): r["nyfed_major"] for r in csv.DictReader(open(ROOT / "spec" / "major73-hc.csv"))
           if r["nyfed_major"]}
    nyfed = [r["Major"] for r in csv.DictReader(
        open(ROOT / "raw/benchmarks/nyfed-2024/college-labor-outcomes-by-major-data.csv", encoding="utf-8-sig"))]
    majors = sorted(m for m in nyfed if m != "Overall")
    print(f"loading ACS {YEAR} 1-year with 80 replicate weights ...", flush=True)
    df = load()
    df["g"] = df.FOD1P.map(lambda c: m73.get(int(c)) if pd.notna(c) else None)
    df = df[df.g.isin(majors)].reset_index(drop=True)
    gi = df.g.map({m: i for i, m in enumerate(majors)}).to_numpy()
    W = df[WCOLS].to_numpy(float)
    adj = df.ADJINC.unique()
    assert len(adj) == 1, "ADJINC varies within the file"
    adj = float(adj[0]) / 1e6
    print(f"  {len(df):,} persons aged 22-45 with a BA or more in the 73 groups; ADJINC {adj}")

    out, flat = {}, []
    # Pay: 2 ages x 2 switches
    base = ((df.SCH == 1) & df.ESR.isin([1, 2, 4, 5]) & (df.WAGP >= 5500)).to_numpy()
    for key, (lo_age, hi_age) in {"pay_mid": (35, 45), "pay_early": (22, 27)}.items():
        for grad, ft in itertools.product([False, True], [True, False]):
            m = base & df.AGEP.between(lo_age, hi_age).to_numpy() & ((df.SCHL >= 21) if grad else (df.SCHL == 21)).to_numpy()
            if ft:
                m &= ((df.WKHP >= 35) & (df.WKWN >= 40)).to_numpy()
            test, shown, n = np.zeros((73, 81)), np.zeros(73), np.zeros(73)
            for i in range(73):
                s = m & (gi == i)
                lower, interp = medians(df.WAGP.to_numpy(float)[s], W[s])
                test[i], shown[i], n[i] = interp, lower[0] * adj, s.sum()
            out[f"{key}|grad={int(grad)}|fulltime={int(ft)}"] = summarize(majors, test, shown, n, "higher")

    # Rates: shares by major, every weight column at once
    def shares(num, den):
        N, D = np.zeros((73, 81)), np.zeros((73, 81))
        np.add.at(N, gi, num[:, None] * W)
        np.add.at(D, gi, den[:, None] * W)
        cnt = np.bincount(gi, weights=den, minlength=73)
        return 100 * N / D, cnt, np.bincount(gi, weights=num, minlength=73)

    young = (df.AGEP.between(22, 27) & (df.SCH == 1)).to_numpy()
    rate, cnt, cnum = shares((young & (df.ESR == 3).to_numpy()).astype(float),
                       (young & df.ESR.isin([1, 2, 3, 4, 5]).to_numpy()).astype(float))
    out["unemployment"] = summarize(majors, rate, rate[:, 0], cnt, "lower", cnum)

    labels = json.loads((ROOT / "raw/benchmarks/census-codelists" / f"SOCP-{YEAR}.json").read_text())["values"]["item"]
    flags = socp_flags([c for c in labels if c.strip() and not c.startswith("b")],
                       soc6_scores(onet_scores(ONET_RELEASE), LINK))
    score = df.SOCP.map(lambda c: flags.get(c, (np.nan, 0, ""))[0]).to_numpy(float)
    emp = young & df.ESR.isin([1, 2, 4, 5]).to_numpy() & ~np.isnan(score)
    rate, cnt, cnum = shares((emp & (score < 50)).astype(float), emp.astype(float))
    out["underemployment"] = summarize(majors, rate, rate[:, 0], cnt, "lower", cnum)

    dest = ROOT / "output" / "panels"
    dest.mkdir(parents=True, exist_ok=True)
    meta = dict(data=f"ACS {YEAR} 1-year PUMS, national", spec="spec/rank-panel.yaml", majors=73,
                dollars=f"{YEAR} dollars (WAGP x ADJINC {adj})", margin="90% (1.645 x SE), SDR 80 replicates",
                underemployment=f"our definition: O*NET {ONET_RELEASE.replace('_', '.')}, {LINK}")
    (dest / f"rank-{YEAR}.json").write_text(json.dumps(dict(meta=meta, measures=out), indent=1))
    with (dest / f"rank-{YEAR}.csv").open("w", newline="") as fh:
        wr = None
        for setting, rows in out.items():
            for r in rows:
                r = dict(setting=setting, **r)
                if wr is None:
                    wr = csv.DictWriter(fh, fieldnames=list(r))
                    wr.writeheader()
                wr.writerow(r)

    print("\nHidden cells (D5) and checks, per measure and setting:")
    for setting, rows in out.items():
        econ = next(r for r in rows if r["major"] == "Economics")
        outside = sum(not (r["rank_lo"] <= r["rank"] <= r["rank_hi"]) for r in rows)
        print(f"  {setting:32} hidden {sum(r['hidden'] for r in rows):2}/73"
              f" | rank outside its range {outside} | Economics: {econ['estimate']:>9} rank {econ['rank']}"
              f" ({econ['rank_lo']}-{econ['rank_hi']}), about the same as {econ['n_about_same']}, hidden={econ['hidden']}")
    print(f"\nwrote output/panels/rank-{YEAR}.json and .csv; elapsed {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main()
