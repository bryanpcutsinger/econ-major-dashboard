"""Done check 1, underemployment: calibrate the NY Fed rate by major against frozen O*NET releases.

Calibration, not replication (no published code). Link rules = ledger E25, corrected by E26
before the rerun: O*NET score = % saying Bachelor's or more is required (RL categories 6-12); a
college job if score >= 50. Detailed SOCP <-> O*NET-SOC by `6digit` (.00 only) or
`8digit_mean`; group codes (trailing 0s) and broad codes (X/Y) = mean of the fitting codes
with no SOCP code of their own, widened to the 3-digit minor group if none has data;
military jobs (55xxxx) left out. Sample = the E23 unemployment match.

Usage (repo root):
  python3 scripts/nyfed_underemployment_check.py 2024    # O*NET 30.0-30.2 vs NYF24
  python3 scripts/nyfed_underemployment_check.py 2022    # O*NET 28.0-28.2 vs NYF22

Outputs: output/checks/nyfed-underemployment-<year>.csv (every variant),
-best-cells.csv, and -socp-flags.csv (each job's score and flag in every variant).
Tolerance (spec D1): Overall +-0.2 pt; each major +-0.5 pt.
"""
import csv
import gzip
import io
import itertools
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw" / "benchmarks"
COLS = ["SERIALNO", "SPORDER", "AGEP", "SCHL", "SCH", "ESR", "FOD1P", "SOCP", "PWGTP"]
RELEASES = {2022: ["28_0", "28_1", "28_2"], 2024: ["30_0", "30_1", "30_2"]}
LINKS = ["6digit", "8digit_mean"]


def load(year):
    """Recent graduates (ages 22-27, BA or more, not enrolled, employed), every national person file."""
    z = zipfile.ZipFile(ROOT / "raw" / f"acs1-{year}" / "csv_pus.zip")
    parts = []
    for name in sorted(n for n in z.namelist() if n.startswith("psam_pus") and n.endswith(".csv")):
        with z.open(name) as fh:
            for chunk in pd.read_csv(fh, usecols=COLS, chunksize=500_000,
                                     dtype={"SERIALNO": str, "SOCP": str, "FOD1P": "Int64"}):
                keep = (chunk.AGEP.between(22, 27) & (chunk.SCHL >= 21) & (chunk.SCH == 1)
                        & chunk.ESR.isin([1, 2, 4, 5]))
                parts.append(chunk[keep])
        print(f"  read {name}", flush=True)
    df = pd.concat(parts, ignore_index=True)
    return df.sort_values(["SERIALNO", "SPORDER"], kind="mergesort").reset_index(drop=True)


def benchmark(year):
    if year == 2024:
        text = (RAW / "nyfed-2024/college-labor-outcomes-by-major-data.csv").read_text()
    else:
        f = next((RAW / "nyfed-2022-wayback").glob("college-labor-outcomes-by-major-data_*.csv"))
        raw = f.read_bytes()
        text = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text.replace("\r\n", "\n").replace("\r", "\n"))))
    return {r["Major"]: float(r["Underemployment Rate"]) for r in rows}


def onet_scores(release):
    """{O*NET-SOC code: % saying Bachelor's or more is required} from one frozen release."""
    z = zipfile.ZipFile(RAW / "onet" / f"db_{release}_text.zip")
    name = next(n for n in z.namelist() if n.endswith("/Education, Training, and Experience.txt"))
    d = pd.read_csv(z.open(name), sep="\t", dtype={"O*NET-SOC Code": str, "Scale ID": str})
    d = d[(d["Scale ID"] == "RL") & d["Category"].between(6, 12)]
    return d.groupby("O*NET-SOC Code")["Data Value"].sum().to_dict()


def soc6_scores(scores, link):
    """{6-digit SOC (no dash): score} under one link variant."""
    s = pd.Series(scores)
    soc6 = s.index.str[:7].str.replace("-", "", regex=False)
    if link == "6digit":
        s = s[s.index.str.endswith(".00")]
        return dict(zip(s.index.str[:7].str.replace("-", "", regex=False), s.to_numpy()))
    return s.groupby(soc6).mean().to_dict()


def socp_flags(socp_codes, s6):
    """{SOCP: (score, n_children, prefix used)} by the ledger E26 rule; score NaN = unmapped."""
    exact = {c for c in socp_codes if c.isdigit()}
    out = {}
    for c in socp_codes:
        if c.startswith("55"):  # military: no O*NET education data (E25 (4))
            out[c] = (np.nan, 0, "")
            continue
        # SOC group codes end in 0; Census broad codes end in X/Y. Detailed codes keep all 6 digits.
        prefix = c.rstrip("XY") if not c.isdigit() else c.rstrip("0")
        kids = [v for k, v in s6.items() if k.startswith(prefix) and (k not in exact or k == c)]
        used = prefix
        for n in range(len(prefix) - 1, 2, -1):  # widen to the 3-digit minor group at most
            if kids:
                break
            used = prefix[:n]
            kids = [v for k, v in s6.items() if k.startswith(used)]
        out[c] = (float(np.mean(kids)), len(kids), used) if kids else (np.nan, 0, "")
    return out


def main(year):
    t0 = time.time()
    bench = benchmark(year)
    labels = json.loads((RAW / "census-codelists" / f"SOCP-{year}.json").read_text())["values"]["item"]
    socp_codes = [c for c in labels if c.strip() and not c.startswith("b")]
    m73 = {int(r["fod1p"]): r["nyfed_major"] for r in csv.DictReader(open(ROOT / "spec" / "major73-hc.csv"))
           if r["nyfed_major"]}
    print(f"loading ACS {year} 1-year ...", flush=True)
    df = load(year)
    df["g"] = df.FOD1P.map(lambda c: m73.get(int(c)) if pd.notna(c) else None)
    w = df.PWGTP.to_numpy(float)
    military = df.SOCP.fillna("").str.startswith("55").to_numpy()
    print(f"  {len(df):,} employed recent graduates; military jobs {100 * w[military].sum() / w.sum():.3f}% (weighted)")

    rows, flag_rows, best = [], [], None
    for release, link in itertools.product(RELEASES[year], LINKS):
        flags = socp_flags(socp_codes, soc6_scores(onet_scores(release), link))
        for c, (sc, n, used) in sorted(flags.items()):
            flag_rows.append([release, link, c, labels[c], used, n, round(sc, 2) if sc == sc else "", int(sc >= 50) if sc == sc else ""])
        score = df.SOCP.map(lambda c: flags.get(c, (np.nan, 0))[0]).to_numpy(float)
        mapped = ~np.isnan(score)
        unmapped_civ = float(100 * w[~mapped & ~military].sum() / w.sum())
        non_college = (mapped & (score < 50)).astype(float)
        d = pd.DataFrame({"n": non_college * w, "d": mapped * w, "g": df.g})
        grp = d.dropna(subset=["g"]).groupby("g")[["n", "d"]].sum()
        ours = (100 * grp.n / grp.d).to_dict()
        ours["Overall"] = 100 * float((non_college * w).sum() / (mapped * w).sum())
        gaps = {m: ours.get(m, np.nan) - b for m, b in bench.items()}
        maj = [abs(v) for m, v in gaps.items() if m != "Overall"]
        row = dict(release=release.replace("_", "."), link=link, within_05=sum(v <= 0.5 for v in maj), cells=len(maj),
                   worst_pt=round(max(maj), 3), overall_ours=round(ours["Overall"], 3),
                   overall_nyfed=bench["Overall"], overall_gap_pt=round(gaps["Overall"], 3),
                   unmapped_civilian_pct=round(unmapped_civ, 4))
        rows.append(row)
        if best is None or (row["within_05"], -row["worst_pt"]) > (best[0]["within_05"], -best[0]["worst_pt"]):
            best = (row, ours)

    out = ROOT / "output" / "checks"
    out.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (-r["within_05"], r["worst_pt"]))
    with (out / f"nyfed-underemployment-{year}.csv").open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    with (out / f"nyfed-underemployment-{year}-socp-flags.csv").open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["release", "link", "socp", "label", "prefix_used", "n_onet_children", "score_ba_plus", "college_job"])
        wr.writerows(flag_rows)
    row, ours = best
    with (out / f"nyfed-underemployment-{year}-best-cells.csv").open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["major", "nyfed", "ours", "gap_pt"])
        for m, b in bench.items():
            wr.writerow([m, b, round(ours.get(m, np.nan), 3), round(ours.get(m, np.nan) - b, 3)])

    print("\nVariants (majors within +-0.5 pt of 73; worst gap; Overall; unmapped civilian %):")
    for r in rows:
        print("  ", r)
    print(f"\n{len(rows)} variants logged to output/checks/nyfed-underemployment-{year}.csv; elapsed {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main(int(sys.argv[1]))
