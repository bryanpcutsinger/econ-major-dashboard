"""Step 8: the 2020-24 5-year panels and bundle v1.

Spec: spec/acs5-panels.yaml (written 2026-10-25 before any estimate; ledger E33-E35). Builds
  - same occupation (panel 3): each major's top 10 jobs; economics vs the major vs everyone in the
    job, ages 25-54 reweighted to the job's age mix (D4); graduate switch
  - local (panel 5): Florida and South Florida; economics vs the major vs all majors; 4 switch settings
and, for the instructor calls, the variants (G1 South Florida PUMAs, L1 local ages, P1 pay measure,
D4 check ages 35-45). Every cell: n, estimate, SDR SE and MOE from PWGTP1-80, hidden flag + reason.

Run from the repo root (after scripts/extract_acs5.py):  python3 scripts/build_acs5_panels.py
Reads cache/acs5-2020-2024-ba.parquet, spec/, raw/benchmarks/ (read-only).
Writes data/bundles/<bundle id>/ and output/checks/acs5-variants.json. It does not publish:
scripts/publish.py runs the step-9 gates, then writes data/current.json (spec/gates.yaml).
"""
import csv
import hashlib
import math
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_rank_panel import major_map, medians  # noqa: E402  (one map rule and one median rule for the page)
from occp_labels import census_occp_labels  # noqa: E402
from vintage import V  # noqa: E402  (spec/vintage.json; spec/scheduler.yaml 11.1)

REPS = [f"PWGTP{r}" for r in range(1, 81)]
WCOLS = ["PWGTP"] + REPS                      # column 0 = full-sample weight
Z90 = 1.645
ECON = "Economics"
SF_COUNTIES = {"086", "011", "099"}           # Miami-Dade, Broward, Palm Beach
EXTRA_SF_PUMA = "08625"                       # Monroe County + 10 Miami-Dade tracts (G1 variant)
STATS = {"neg_weight_cells": 0}


# ---------- cells, differences, labels (spec: common) ----------

def sdr(t):
    return float(np.sqrt(4 / 80 * ((t[1:] - t[0]) ** 2).sum()))


def cell(v, W):
    """Median cell: lower median shown, interpolated median for the SE (negative replicate weights = 0)."""
    n = len(v)
    if n == 0:
        return {"n": 0, "hidden": True, "reason": "no people"}, None
    STATS["neg_weight_cells"] += bool((W < 0).any())
    lower, interp = medians(v, np.maximum(W, 0))
    est, se = float(lower[0]), sdr(interp)
    reason = "n < 100" if n < 100 else ("MOE / estimate > 0.30" if Z90 * se / est > 0.30 else "")
    if not np.isfinite(se):
        reason = "replicate weights sum to 0"
    out = {"n": n, "median": round(est, 2), "se": round(se, 2), "moe": round(Z90 * se, 2),
           "hidden": bool(reason), "reason": reason}
    return out, interp


def compare(a, b):
    """Economics (a) minus other (b), inside each replicate; label only if both cells show."""
    (ca, ta), (cb, tb) = a, b
    if ca["hidden"] or cb["hidden"]:
        return {"label": None}
    d = ta - tb
    se = sdr(d)
    lab = "better" if d[0] > Z90 * se else ("worse" if d[0] < -Z90 * se else "about the same")
    return {"d": round(float(d[0]), 2), "se": round(se, 2), "moe": round(Z90 * se, 2), "label": lab}


def ratio(num, den):
    """Weighted share (81 columns) with its SDR SE."""
    r = num / den
    return {"share": round(float(r[0]), 6), "se": round(sdr(r), 6), "moe": round(Z90 * sdr(r), 6)}


# ---------- age reweighting (spec: same_occupation.age_reweighting, D4) ----------

def reweight(W, age, target_age, target_w):
    """Weight a group to the target's age mix. Factors from PWGTP only, applied to all 81 columns.

    Bins of 5 years (25-29 ... 50-54), then of 10 (25-34, 35-44, 45-54); None if a target bin is empty
    in the group at both widths (cell hidden: 'age mix').
    """
    for width in (5, 10):
        nb = 30 // width
        tb = np.bincount((target_age - 25) // width, weights=target_w, minlength=nb)
        gb = np.bincount((age - 25) // width, weights=W[:, 0], minlength=nb)
        if np.any((tb > 0) & (gb <= 0)):
            continue
        f = np.where(gb > 0, (tb / tb.sum()) / np.where(gb > 0, gb / gb.sum(), 1), 0)
        return W * f[(age - 25) // width][:, None]
    return None


def age_cell(d, idx, tgt_idx, reweight_on):
    v, W, age = d["pay"][idx], d["W"][idx], d["AGEP"][idx]
    if reweight_on and len(idx):
        W2 = reweight(W, age, d["AGEP"][tgt_idx], d["W"][tgt_idx, 0])
        if W2 is None:
            return {"n": len(idx), "hidden": True, "reason": "age mix"}, None
        W = W2
    return cell(v, W)


# ---------- data ----------

def load():
    df = pd.read_parquet(V.cache)
    m73, majors = major_map()
    df["g"] = df.FOD1P.map(lambda c: m73.get(int(c)))
    adj = df.ADJINC.to_numpy(float) / 1e6
    df["pay_wagp"] = df.WAGP.to_numpy(float) * adj        # D2: 2024 dollars
    df["pay_pernp"] = df.PERNP.to_numpy(float) * adj
    return df, majors


def arrays(s, pay_col):
    """Numpy views of one sample, sorted as the extract (SERIALNO, SPORDER)."""
    return {"pay": s[pay_col].to_numpy(float), "W": s[WCOLS].to_numpy(float), "AGEP": s.AGEP.to_numpy(int),
            "g": s.g.to_numpy(object), "OCCP": s.OCCP.astype(int).to_numpy()}


def base_mask(df, grad, fulltime, ages, pay_col, threshold=5500, strict=False):
    m = (df.SCH == 1) & df.ESR.isin([1, 2, 4, 5]) & df.AGEP.between(*ages)
    m &= (df.SCHL >= 21) if grad else (df.SCHL == 21)
    if fulltime:
        m &= (df.WKHP >= 35) & (df.WKWN >= 40)
    m &= (df[pay_col] > threshold) if strict else (df[pay_col] >= threshold)
    return m.to_numpy()


# ---------- panel 3: same occupation ----------

def index_by(keys):
    """{key: row indices} for an array of keys."""
    o = np.argsort(keys, kind="mergesort")
    u, starts = np.unique(keys[o], return_index=True)
    return dict(zip(u.tolist(), np.split(o, starts[1:])))


def top_jobs(d, idx):
    """Top 10 OCCP by weighted count (ties -> lower code)."""
    w = pd.Series(d["W"][idx, 0]).groupby(d["OCCP"][idx]).sum()
    return sorted(w.index.tolist(), key=lambda o: (-w[o], o))[:10]


def same_occupation(df, majors, occ_label, grad, ages, reweight_on, pay_col, rows_from=None):
    s = df[base_mask(df, grad, True, ages, pay_col)].reset_index(drop=True)
    d = arrays(s, pay_col)
    by_g = {m: np.flatnonzero(d["g"] == m) for m in majors}
    by_o = index_by(d["OCCP"])
    none = np.array([], int)
    tops = rows_from or {m: top_jobs(d, by_g[m]) for m in majors}
    cache = {}

    def get(grp, o):
        key = (grp, o)
        if key not in cache:
            tgt = by_o.get(o, none)
            if grp == "all":
                cache[key] = cell(d["pay"][tgt], d["W"][tgt])
            else:
                idx = tgt[d["g"][tgt] == grp]
                cache[key] = age_cell(d, idx, tgt, reweight_on)
        return cache[key]

    out = {}
    for m in majors:
        tot = d["W"][by_g[m]].sum(axis=0)
        lists = {}
        for which, rows in (("major_top", tops[m]), ("economics_top", tops[ECON])):
            lst = []
            for o in rows:
                e, a = get(ECON, o), get("all", o)
                row = {"occp": int(o), "label": occ_label[int(o)],
                       "major_share": ratio(d["W"][by_o.get(o, none)[d["g"][by_o.get(o, none)] == m]].sum(axis=0), tot),
                       "economics": e[0], "all": a[0], "econ_vs_all": compare(e, a)}
                if m != ECON:
                    mm = get(m, o)
                    row["major"] = mm[0]
                    row["econ_vs_major"] = compare(e, mm)
                lst.append(row)
            key = "econ_vs_major" if m != ECON else "econ_vs_all"
            labs = [r[key]["label"] for r in lst]
            lists[which] = {"rows": lst, "headline": {k: labs.count(k) for k in ("better", "about the same", "worse")},
                            "hidden_rows": labs.count(None)}
        out[m] = {"n": int(len(by_g[m])), **lists}
    present = sum(len(by_g[m]) > 0 for m in majors)
    return out, tops, present


# ---------- panel 5: local ----------

def local(df, majors, areas, grad, fulltime, ages, reweight_on, pay_col):
    out = {}
    for area, amask in areas.items():
        s = df[base_mask(df, grad, fulltime, ages, pay_col) & amask].reset_index(drop=True)
        d = arrays(s, pay_col)
        everyone = np.arange(len(s))
        a = cell(d["pay"], d["W"])
        e = age_cell(d, np.flatnonzero(d["g"] == ECON), everyone, reweight_on)
        rows = {}
        for m in majors:
            mm = age_cell(d, np.flatnonzero(d["g"] == m), everyone, reweight_on) if m != ECON else e
            rows[m] = {"major": mm[0], "econ_vs_major": compare(e, mm) if m != ECON else {"label": None}}
        out[area] = {"economics": e[0], "all": a[0], "econ_vs_all": compare(e, a), "by_major": rows,
                     "majors_present": sum(r["major"]["n"] > 0 for r in rows.values())}
    return out


# ---------- lifetime earnings (spec/lifetime-panel.yaml; Julian and Kominski 2011) ----------

BANDS = [(a, a + 4) for a in range(25, 65, 5)]            # 25-29 ... 60-64


def worklife(band_medians):
    """J&K synthetic work-life earnings: each 5-year band's median x 5, summed (pp. 1, 4-5, 13). math.fsum, not sum:
    Python 3.12's sum() of floats differs from 3.9's in the last bits, which moved 12 totals by a cent (E53)."""
    return 5 * math.fsum(band_medians)


def lifetime_mask(df):
    """Ages 25-64, full-time year-round (WKHP >= 35, WKWN >= 50), with earnings (PERNP != 0). No other filter."""
    return (df.AGEP.between(25, 64) & (df.WKHP >= 35) & (df.WKWN >= 50) & (df.PERNP != 0)).to_numpy()


def lifetime_cell(pay, W, age):
    """One group: the shown total (lower band medians) and its 81-column test statistic (interpolated medians)."""
    W0 = np.maximum(W, 0)                                   # negative replicate weights = 0 inside medians only
    bands, shown, T, reason = [], [], np.zeros(W.shape[1]), ""
    for lo, hi in BANDS:
        m = (age >= lo) & (age <= hi)
        k = int(m.sum())
        if k == 0:
            return {"n": int(len(age)), "hidden": True, "reason": f"no people aged {lo}-{hi}", "bands": []}, None
        lower, interp = medians(pay[m], W0[m])
        bands.append({"ages": f"{lo}-{hi}", "median": round(float(lower[0]), 2), "n": k})
        shown.append(float(lower[0]))
        T += 5 * interp
        if k < 100 and not reason:
            reason = f"fewer than 100 people aged {lo}-{hi}"
    total, se = worklife(shown), sdr(T)
    if not reason and Z90 * se / total > 0.30:
        reason = "MOE / estimate > 0.30"
    return {"total": round(total, 2), "se": round(se, 2), "moe": round(Z90 * se, 2), "n": int(len(age)),
            "hidden": bool(reason), "reason": reason, "bands": bands}, T


def lifetime(df, majors):
    """Economics, each major, and all bachelor's (high school dropped 2026-10-26, instructor; ledger E48)."""
    out = {}
    for grad in (False, True):
        s = df[lifetime_mask(df) & ((df.SCHL >= 21) if grad else (df.SCHL == 21)).to_numpy() & df.g.isin(majors).to_numpy()]
        pay, W, age, g = s.pay_pernp.to_numpy(float), s[WCOLS].to_numpy(float), s.AGEP.to_numpy(int), s.g.to_numpy(object)
        cells = {m: lifetime_cell(pay[g == m], W[g == m], age[g == m]) for m in majors}
        allc, econ = lifetime_cell(pay, W, age), cells[ECON]
        out[f"grad={int(grad)}"] = {
            "economics": econ[0], "all_bachelors": allc[0], "econ_vs_all": compare(econ, allc),
            "by_major": {m: {"major": cells[m][0], "econ_vs_major": compare(econ, cells[m])} for m in majors if m != ECON}}
    return out, int((lifetime_mask(df) & (df.PERNP < 0).to_numpy()).sum())


# ---------- bundle ----------

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def dump(obj):
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main():
    t0 = time.time()
    df, majors = load()
    occ_label = census_occp_labels(V.dict5)   # E45: Census labels

    # Gates (spec: gates)
    fod_unmapped = df.g.isna() & (df.FOD1P != 0)
    gates = {"fod1p_unmapped_persons": int(fod_unmapped.sum()),
             "occp_without_label": sorted({int(c) for c in df.OCCP.dropna()} - set(occ_label))}
    tract = pd.read_csv(V.tract_puma, dtype=str,
                        encoding="utf-8-sig")
    fl = tract[tract.STATEFP == "12"]
    inside = sorted(p for p, cs in fl.groupby("PUMA5CE").COUNTYFP.apply(set).items() if cs <= SF_COUNTIES)
    gates["south_florida_pumas"] = len(inside)
    print("gates:", gates, flush=True)

    in_fl = (df.STATE == "12").to_numpy()
    areas = {"florida": in_fl, "south_florida": in_fl & df.PUMA.isin(inside).to_numpy()}

    bundle, variants = {}, {}
    # Panel 3, default (D4: ages 25-54 reweighted; wages)
    so, tops, present = {}, {}, {}
    for grad in (False, True):
        k = f"grad={int(grad)}"
        so[k], tops[k], present[k] = same_occupation(df, majors, occ_label, grad, (25, 54), True, "pay_wagp")
        print(f"  same occupation {k}: {time.time() - t0:.0f} s", flush=True)
    gates["same_occupation_majors_present"] = present
    bundle["same_occupation"] = so
    # D4 check (35-45, no reweighting) and P1 (earnings), on the default rows, graduate switch off
    variants["same_occupation_ages_35_45"] = same_occupation(df, majors, occ_label, False, (35, 45), False,
                                                             "pay_wagp", rows_from=tops["grad=0"])[0]
    variants["same_occupation_pernp"] = same_occupation(df, majors, occ_label, False, (25, 54), True,
                                                        "pay_pernp", rows_from=tops["grad=0"])[0]
    print(f"  same occupation variants: {time.time() - t0:.0f} s", flush=True)

    # Panel 5, default (L1: 25-54 reweighted; G1: 52 PUMAs; P1: wages), 4 switch settings
    loc = {}
    for grad in (False, True):
        for ft in (True, False):
            loc[f"grad={int(grad)}|fulltime={int(ft)}"] = local(df, majors, areas, grad, ft, (25, 54), True, "pay_wagp")
    bundle["local"] = loc
    dflt = "grad=0|fulltime=1"
    variants["local_ages_35_45"] = local(df, majors, areas, False, True, (35, 45), False, "pay_wagp")
    variants["local_pernp"] = local(df, majors, areas, False, True, (25, 54), True, "pay_pernp")
    variants["local_sf_with_08625"] = local(df, majors, {"south_florida": in_fl & df.PUMA.isin(inside + [EXTRA_SF_PUMA]).to_numpy()},
                                            False, True, (25, 54), True, "pay_wagp")
    print(f"  local: {time.time() - t0:.0f} s", flush=True)
    life, life_negative = lifetime(df, majors)
    print(f"  lifetime: {time.time() - t0:.0f} s", flush=True)

    # HC Tables 1-3 rolled forward: dropped 2026-10-25 (instructor; ledger E40). No panel used them; the replication stays in output/checks.

    # Cross-check (warning only): national economics mid-career pay, rank-panel rules, 5-year vs 1-year
    s = df[base_mask(df, False, True, (35, 45), "pay_wagp") & (df.g == ECON).to_numpy()]
    c5 = cell(s.pay_wagp.to_numpy(float), s[WCOLS].to_numpy(float))[0]
    rank = json.loads(V.rank_json.read_text())
    r1 = next(r for r in rank["measures"]["pay_mid|grad=0|fulltime=1"] if r["major"] == ECON)
    variants["cross_check_econ_mid_pay"] = {f"acs5_{V.a5}_{str(V.b5)[2:]}": c5, f"acs1_{V.y1}_rank_panel": {"estimate": r1["estimate"], "se": r1["se"], "n": r1["n"]}}
    gates["negative_weight_cells"] = STATS["neg_weight_cells"]

    # Bundle v1 (spec: bundle_v1). INDP stays in the code list (a bundle id input), though no panel uses it (E40)
    codes = {"FOD1P": sorted({int(c) for c in df.FOD1P}), "OCCP": sorted({int(c) for c in df.OCCP.dropna()}),
             "INDP": sorted({int(c) for c in df.INDP.dropna()}),
             "PUMA": sorted(set(df.STATE + df.PUMA))}
    codehash = hashlib.sha256(json.dumps(codes, sort_keys=True).encode()).hexdigest()[:8]
    # Step 9 (spec/gates.yaml bundle_additions): code lists and counts the gates compare, no microdata
    prof1 = json.loads(V.rank_profile.read_text())
    files = {"rank.json": V.rank_json.read_bytes(),
             # Step 10 (spec/front-end.yaml panel_1_addition): the side-by-side panel, from the same 1-year build
             "compare.json": V.compare_json.read_bytes(),
             "codes.json": dump({"acs5": codes, "acs1": {"FOD1P": prof1["FOD1P"], "SOCP": prof1["SOCP"]},
                                 "south_florida_pumas": inside}).encode(),
             "same_occupation.json": dump(bundle["same_occupation"]).encode(),
             "local.json": dump(bundle["local"]).encode(),
             "lifetime.json": dump(life).encode()}
    # Bundle id = years + code-list hash + data hash (2026-10-26, ledger E43): a rebuild with new numbers
    # gets a new folder, so a published bundle is never overwritten and rollback keeps its target.
    # Bundle v1 (2024-1yr_2020-24-5yr_6f8bddb5) predates the data hash.
    datahash = hashlib.sha256("".join(f"{k}:{hashlib.sha256(v).hexdigest()}\n" for k, v in sorted(files.items()))
                              .encode()).hexdigest()[:6]
    bid = f"{V.bundle_prefix}{codehash}-{datahash}"
    out = ROOT / "data" / "bundles" / bid
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    stats = {"acs1": {k: v for k, v in prof1.items() if k not in ("FOD1P", "SOCP")},
             "acs5": {"records_kept": len(df), "pwgtp_sum": int(df.PWGTP.sum()),
                      "fod1p_unmapped_persons": gates["fod1p_unmapped_persons"],
                      "lifetime_negative_pernp": life_negative}}
    dicts = {"acs1": sha(V.dict1), "acs5": sha(V.dict5)}
    # 11.2: each source's url, bytes, Last-Modified, sha256 (raw/<sid>/PROVENANCE.txt) and its dictionary (spec/inputs.json),
    # so H9 and the probe compare against the live bundle itself, not a file the bot would have to rewrite
    inputs = json.loads((ROOT / "spec" / "inputs.json").read_text())
    def record(zip_path, dict_path):
        prov = dict(line.split(": ", 1) for line in (zip_path.parent / "PROVENANCE.txt").read_text().splitlines() if ": " in line)
        d = inputs[str(dict_path.relative_to(ROOT))]
        return {"url": prov["source"], "bytes": int(prov["bytes"]), "last_modified": prov["last_modified_header"],
                "sha256": prov["sha256"], "dictionary": {"url": d["url"], "bytes": d["bytes"], "sha256": d["sha256"]}}
    source_records = {V.acs1_id: record(V.acs1_zip, V.dict1), V.acs5_id: record(V.acs5_zip, V.dict5)}
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "scripts", "spec"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip())
    manifest = {"bundle": bid, "git_commit": git, "worktree_dirty": dirty, "gates": gates,
                "stats": stats, "dictionaries": dicts,
                "dollars": f"{V.dollar_year} dollars (ADJINC)", "years": V.years,
                "sources": {str(z.relative_to(ROOT)): sha(z) for z in V.pums}, "source_records": source_records,
                "spec": {p: sha(ROOT / p) for p in ["spec/acs5-panels.yaml", "spec/rank-panel.yaml", "spec/major73.csv",
                                                     "spec/front-end.yaml", "spec/vintage.json",
                                                     "spec/lifetime-panel.yaml"]},
                "code": {p: sha(ROOT / p) for p in ["scripts/build_acs5_panels.py", "scripts/build_rank_panel.py",
                                                     "scripts/occp_labels.py", "scripts/extract_acs5.py",
                                                     "scripts/vintage.py"]},
                "files": {f.name: sha(f) for f in sorted(out.glob("*.json")) if f.name != "manifest.json"}}
    (out / "manifest.json").write_text(dump(manifest))
    (ROOT / "output" / "checks" / "acs5-variants.json").write_text(dump(variants))
    print(f"wrote data/bundles/{bid}/ ({len(manifest['files']) + 1} files); {time.time() - t0:.0f} s")
    print("gates:", json.dumps(gates))


if __name__ == "__main__":
    main()
