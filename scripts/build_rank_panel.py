"""Build the rank panel: where each of the 73 majors ranks on four measures, with uncertainty.

Spec: spec/rank-panel.yaml (written before any result; two instructor rulings after the first
build). For each measure and switch setting: the estimate, its SDR standard error from
PWGTP1-80, the unweighted n, the hide flag (D5 for pay, a count rule for rates), and the
point rank (the page shows this). Audit only: a 90% rank range from pairwise tests and the
number of majors "about the same".

Also (step 10, spec/front-end.yaml panel_1_addition): the side-by-side panel's numbers for the default
settings: economics, each major, and all majors, with every difference taken inside each replicate.

Run from the repo root:  python3 scripts/build_rank_panel.py
Reads raw/ (read-only); writes output/panels/rank-2024.{json,csv}, rank-2024-profile.json (counts and
code lists for the step-9 gates), and compare-2024.json.
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

MAJOR_MAP = ROOT / "spec" / "major73.csv"     # our map (E45: replaces the authors' map in every page build)


def major_map():
    """{FOD1P: major} and the 73 major names, both from spec/major73.csv (no NY Fed file needed on the runner)."""
    m73 = {int(r["fod1p"]): r["nyfed_major"] for r in csv.DictReader(open(MAJOR_MAP)) if r["nyfed_major"]}
    majors = sorted(set(m73.values()))
    assert len(majors) == 73, f"{len(majors)} majors in {MAJOR_MAP.name}"
    return m73, majors


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
            moe_ratio=round(float(moe_ratio), 3), n_num=None if n_num is None else int(n_num[i]),
            hidden=bool(n[i] < 100 or (moe_ratio > 0.30 if n_num is None else min(n_num[i], n[i] - n_num[i]) < 10)),
            rank=1 + int((sign * (shown - est) > 0).sum()), rank_lo=lo, rank_hi=hi,
            n_about_same=len(majors) - 1 - int(sig_better[i].sum()) - int(sig_worse[i].sum())))
    return rows


def sdr(t):
    return float(np.sqrt(4 / 80 * ((t[1:] - t[0]) ** 2).sum()))


def cmp_cell(kind, test, shown, n, n_num=None):
    """One panel-1 cell. Pay: shown = lower median, SE from the interpolated median (both 2024 dollars).
    Rates: the rate and the rank panel's count hide rule."""
    se = round(sdr(test), 4)
    out = {"n": int(n), "se": se, "moe": round(Z90 * se, 6)}
    if kind == "pay":
        reason = "n < 100" if n < 100 else ("MOE / estimate > 0.30" if Z90 * se / shown > 0.30 else "")
        out["median"] = round(float(shown), 2)
    else:
        reason = "n < 100" if n < 100 else (
            "fewer than 10 people in the numerator or its complement" if min(n_num, n - n_num) < 10 else "")
        out.update(rate=round(float(test[0]), 4), n_num=int(n_num))
    return dict(out, hidden=bool(reason), reason=reason)


def cmp_diff(better, ta, tb, ca, cb):
    """Economics (a) vs other (b) inside each replicate. d is oriented: positive = economics better."""
    if ca["hidden"] or cb["hidden"]:
        return {"label": None}
    d = (ta - tb) if better == "higher" else (tb - ta)
    se = round(sdr(d), 4)
    moe = round(Z90 * se, 6)
    lab = "better" if d[0] > moe else ("worse" if d[0] < -moe else "about the same")
    return {"d": round(float(d[0]), 4), "se": se, "moe": moe, "label": lab}


def compare_measure(majors, kind, better, setting, test, shown, n, all_test, all_shown, all_n,
                    n_num=None, all_num=None):
    cells = [cmp_cell(kind, test[i], shown[i], n[i], None if n_num is None else n_num[i]) for i in range(73)]
    e = majors.index("Economics")
    allc = cmp_cell(kind, all_test, all_shown, all_n, all_num)
    by = {m: {"major": cells[i], "econ_vs_major": cmp_diff(better, test[e], test[i], cells[e], cells[i])}
          for i, m in enumerate(majors) if i != e}
    return {"kind": kind, "better": better, "setting": setting, "economics": cells[e], "all": allc,
            "econ_vs_all": cmp_diff(better, test[e], all_test, cells[e], allc), "by_major": by}


def main():
    t0 = time.time()
    m73, majors = major_map()
    print(f"loading ACS {YEAR} 1-year with 80 replicate weights ...", flush=True)
    df = load()
    df["g"] = df.FOD1P.map(lambda c: m73.get(int(c)) if pd.notna(c) else None)
    # Step 9 side file (spec/gates.yaml H2, H7): counts and code lists before the 73-group filter
    profile = {"records_kept": len(df), "pwgtp_sum": int(df.PWGTP.sum()),
               "fod1p_unmapped_persons": int((df.FOD1P.notna() & df.g.isna()).sum()),
               "fod1p_missing_persons": int(df.FOD1P.isna().sum()),
               "FOD1P": sorted({int(c) for c in df.FOD1P.dropna()})}
    df = df[df.g.isin(majors)].reset_index(drop=True)
    gi = df.g.map({m: i for i, m in enumerate(majors)}).to_numpy()
    W = df[WCOLS].to_numpy(float)
    W0 = np.maximum(W, 0)                         # E35: negative replicate weights = 0 inside medians only
    adj = df.ADJINC.unique()
    assert len(adj) == 1, "ADJINC varies within the file"
    adj = float(adj[0]) / 1e6
    print(f"  {len(df):,} persons aged 22-45 with a BA or more in the 73 groups; ADJINC {adj}")

    out, flat, cmp = {}, [], {}
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
                lower, interp = medians(df.WAGP.to_numpy(float)[s], W0[s])
                test[i], shown[i], n[i] = interp * adj, lower[0] * adj, s.sum()   # E36: SEs in 2024 dollars
            out[f"{key}|grad={int(grad)}|fulltime={int(ft)}"] = summarize(majors, test, shown, n, "higher")
            if not grad and ft:                                   # panel 1 = the NY Fed wage definition
                lower, interp = medians(df.WAGP.to_numpy(float)[m], W0[m])
                cmp[key] = compare_measure(majors, "pay", "higher", f"grad=0|fulltime=1, ages {lo_age}-{hi_age}",
                                           test, shown, n, interp * adj, lower[0] * adj, m.sum())

    # Rates: shares by major, every weight column at once
    def shares(num, den):
        N, D = np.zeros((73, 81)), np.zeros((73, 81))
        np.add.at(N, gi, num[:, None] * W)
        np.add.at(D, gi, den[:, None] * W)
        cnt = np.bincount(gi, weights=den, minlength=73)
        return 100 * N / D, cnt, np.bincount(gi, weights=num, minlength=73)

    young = (df.AGEP.between(22, 27) & (df.SCH == 1)).to_numpy()
    def all_rate(num, den):
        """All 73 groups pooled, every weight column; unweighted counts."""
        return 100 * (num[:, None] * W).sum(axis=0) / (den[:, None] * W).sum(axis=0), den.sum(), num.sum()

    num, den = (young & (df.ESR == 3).to_numpy()).astype(float), (young & df.ESR.isin([1, 2, 3, 4, 5]).to_numpy()).astype(float)
    rate, cnt, cnum = shares(num, den)
    out["unemployment"] = summarize(majors, rate, rate[:, 0], cnt, "lower", cnum)
    ar, an, anum = all_rate(num, den)
    cmp["unemployment"] = compare_measure(majors, "rate", "lower", "ages 22-27, bachelor's or higher, not enrolled",
                                          rate, rate[:, 0], cnt, ar, ar[0], an, cnum, anum)

    labels = json.loads((ROOT / "raw/benchmarks/census-codelists" / f"SOCP-{YEAR}.json").read_text())["values"]["item"]
    flags = socp_flags([c for c in labels if c.strip() and not c.startswith("b")],
                       soc6_scores(onet_scores(ONET_RELEASE), LINK))
    score = df.SOCP.map(lambda c: flags.get(c, (np.nan, 0, ""))[0]).to_numpy(float)
    emp = young & df.ESR.isin([1, 2, 4, 5]).to_numpy() & ~np.isnan(score)
    num, den = (emp & (score < 50)).astype(float), emp.astype(float)
    rate, cnt, cnum = shares(num, den)
    out["underemployment"] = summarize(majors, rate, rate[:, 0], cnt, "lower", cnum)
    ar, an, anum = all_rate(num, den)
    cmp["underemployment"] = compare_measure(majors, "rate", "lower", "ages 22-27, bachelor's or higher, employed, not enrolled",
                                             rate, rate[:, 0], cnt, ar, ar[0], an, cnum, anum)
    employed = young & df.ESR.isin([1, 2]).to_numpy()            # civilian jobs (E27 coverage rule)
    profile["SOCP"] = sorted({c.strip() for c in df.SOCP.dropna() if c.strip()})
    profile["civilian_employed_recent_grads"] = int(employed.sum())
    profile["civilian_employed_recent_grads_unscored"] = int((employed & np.isnan(score)).sum())

    dest = ROOT / "output" / "panels"
    dest.mkdir(parents=True, exist_ok=True)
    meta = dict(data=f"ACS {YEAR} 1-year PUMS, national", spec="spec/rank-panel.yaml", majors=73, major_map="spec/major73.csv (ours)",
                dollars=f"{YEAR} dollars (WAGP x ADJINC {adj}; medians and SEs both adjusted)", margin="90% (1.645 x SE), SDR 80 replicates",
                underemployment=f"our definition: O*NET {ONET_RELEASE.replace('_', '.')}, {LINK}")
    (dest / f"rank-{YEAR}.json").write_text(json.dumps(dict(meta=meta, measures=out), indent=1))
    (dest / f"rank-{YEAR}-profile.json").write_text(json.dumps(profile, indent=1, sort_keys=True) + "\n")
    cmeta = dict(meta, spec="spec/front-end.yaml panel_1_addition", majors=73,
                 d="oriented: positive = economics better (pay: economics - other; rates: other - economics)",
                 dollars=f"{YEAR} dollars (WAGP x ADJINC {adj}; medians and SEs both adjusted)")
    (dest / f"compare-{YEAR}.json").write_text(json.dumps(dict(meta=cmeta, measures=cmp), indent=1, sort_keys=True) + "\n")
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
