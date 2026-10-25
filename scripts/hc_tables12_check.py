"""Done check 2, HC Tables 1-2: economics majors' occupations and industry groups (2018-23 pooled).

Rules pre-registered in ledger E30 (with E22, E28) before this script ran. First an exact pin:
HC's econ counts by year (2020 = the experimental-weights file). Then Table 1 (top 40
occupations) and Table 2 (top 20 industry groups): frequency, share, median earnings.

Run from the repo root:  python3 scripts/hc_tables12_check.py
Reads raw/acs1-*/csv_pus.zip (read-only); writes output/checks/hc-table{1,2}.csv.
"""
import csv
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from hc_table3_check import ECON, HC_ECON as HC_ECON_21_23, weighted_median  # noqa: E402  (one median rule)

FOLDERS = {2018: "acs1-2018", 2019: "acs1-2019", 2020: "acs1-2020-experimental",
           2021: "acs1-2021", 2022: "acs1-2022", 2023: "acs1-2023"}
CPI99 = {2018: 0.663, 2019: 0.652, 2020: 0.644, 2021: 0.615, 2022: 0.569, 2023: 0.547}   # IPUMS page, frozen
HC_ECON = {2018: (1323, 137488), 2019: (1446, 142701), 2020: (1188, 158604), **HC_ECON_21_23}
RSCRIPT = ROOT / "raw/benchmarks/hc-2026-openicpsr/ICPSR_241262-V1.0/script_jobs_majors_20251210.R"
# Table 1 notes: * and ** (read by pdftotext as a / b) stand for these endings (ledger E31)
FOOTNOTES = {"a": ", except advertising, insurance, financial services, and travel",
             "b": ", except legal, medical, and executive"}
BLOCKS = {"table1": (121, 652, 40), "table2": (937, 1209, 20)}   # occupation2 on OCCP; industry_category on INDP


def recode_block(first, last):
    """{code: label} from one car::recode block of HC's script (labels trimmed)."""
    text = "\n".join(RSCRIPT.read_text().splitlines()[first - 1:last])
    body = text[text.index('"') + 1:text.rindex('"')]
    return {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"(\d+)\s*=\s*'([^']*)'", body)}


def load(year):
    """Economics majors aged 35-45 with a bachelor's only, one survey year; weeks as a 40+ flag."""
    weeks = "WKW" if year == 2018 else "WKWN"
    cols = ["SERIALNO", "SPORDER", "AGEP", "SCHL", "SCH", "ESR", "WKHP", weeks, "PERNP", "FOD1P",
            "OCCP", "INDP", "PWGTP"]
    z = zipfile.ZipFile(ROOT / "raw" / FOLDERS[year] / "csv_pus.zip")
    parts = []
    for name in sorted(n for n in z.namelist() if n.startswith("psam_pus") and n.endswith(".csv")):
        with z.open(name) as fh:
            for chunk in pd.read_csv(fh, usecols=cols, chunksize=500_000,
                                     dtype={"SERIALNO": str, "FOD1P": "Int64", "OCCP": str, "INDP": str}):
                parts.append(chunk[chunk.AGEP.between(35, 45) & (chunk.SCHL == 21) & chunk.FOD1P.isin(ECON)])
    df = pd.concat(parts, ignore_index=True).sort_values(["SERIALNO", "SPORDER"], kind="mergesort")
    df["weeks40"] = df[weeks].isin([1, 2, 3]) if year == 2018 else df[weeks] >= 40   # WKSWORK2 > 3
    df["YEAR"] = year
    print(f"  read {year} ({FOLDERS[year]}): {len(df):,} econ majors aged 35-45, bachelor's only", flush=True)
    return df.drop(columns=[weeks])


def check_table(s, key, total):
    first, last, top = BLOCKS[key]
    labels = recode_block(first, last)
    code_col = "OCCP" if key == "table1" else "INDP"
    codes = s[code_col].astype(int)
    s = s.assign(grp=codes.map(lambda c: labels.get(c, f"code {c}")))   # unlisted code = its own group
    unlisted = s.grp.str.startswith("code ")
    print(f"\n{key}: {unlisted.sum()} persons in codes the HC block does not list "
          f"({sorted(s.grp[unlisted].unique().tolist())[:12]})")
    freq = s.grp.value_counts()
    pub = list(csv.DictReader(open(ROOT / "raw" / "benchmarks" / "hc-2026" / f"{key}.csv")))
    by_lower = {g.lower(): g for g in freq.index}
    name_col = pub[0].keys().__iter__().__next__()
    rows = []
    for p in pub:
        lab = p[name_col].lower()
        if lab not in by_lower:                               # short labels (ledger E31)
            lab = lab.replace("admin.", "administrative")
            if lab[-1] in FOOTNOTES and lab[:-1] + FOOTNOTES[lab[-1]] in by_lower:
                lab = lab[:-1] + FOOTNOTES[lab[-1]]
        g = by_lower.get(lab)
        f = int(freq[g]) if g else 0
        sub = s[s.grp == g] if g else s.iloc[:0]
        med = float(weighted_median(sub.INCEARNadj.to_numpy(float), sub.PWGTP.to_numpy(float), 2)) if f else np.nan
        share = 100 * f / total
        rows.append(dict(label=p[name_col], matched=g or "", freq_pub=int(p["frequency"]), freq=f,
                         share_pub=float(p["pct_of_majors"]), share=round(share, 4),
                         median_pub=int(p["median_income"]), median=round(med, 2),
                         freq_ok=f == int(p["frequency"]),
                         share_ok=abs(share - float(p["pct_of_majors"])) <= 0.05 + 1e-9,
                         median_exact=bool(abs(med - int(p["median_income"])) <= 0.5),
                         median_within_1pct=bool(abs(med / int(p["median_income"]) - 1) <= 0.01)))
    with (ROOT / "output" / "checks" / f"hc-{key}.csv").open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)

    # Set test (E30 (7)): only swaps among groups tied at the cut frequency are allowed
    cut = int(freq.sort_values(ascending=False, kind="mergesort").iloc[top - 1])
    published = {r["matched"] for r in rows if r["matched"]}
    set_ok = (all(g in published for g, f in freq.items() if f > cut)
              and all(freq.get(g, 0) >= cut for g in published))
    n = len(rows)
    c = lambda k: sum(r[k] for r in rows)
    print(f"{key}: rows matched {sum(bool(r['matched']) for r in rows)}/{n}; top-{top} set "
          f"{'OK' if set_ok else 'DIFFERS'} (cut frequency {cut})")
    print(f"  frequency exact {c('freq_ok')}/{n}; share within 0.05 pt {c('share_ok')}/{n}; "
          f"median exact {c('median_exact')}/{n}, within 1% {c('median_within_1pct')}/{n}")
    for r in rows:
        if not (r["freq_ok"] and r["share_ok"] and r["median_exact"]):
            print(f"    miss: {r['label'][:45]:45} freq {r['freq']} vs {r['freq_pub']}; "
                  f"share {r['share']:.2f} vs {r['share_pub']}; median {r['median']} vs {r['median_pub']}")
    return (set_ok and c("freq_ok") == n and c("share_ok") == n and c("median_exact") >= 0.9 * n
            and c("median_within_1pct") == n)


def main():
    t0 = time.time()
    df = pd.concat([load(y) for y in FOLDERS], ignore_index=True)
    df["INCEARNadj"] = df.PERNP * df.YEAR.map(CPI99) * 1.797    # HC line 71, same order
    s = df[(df.SCH == 1) & df.ESR.isin([1, 2, 4, 5]) & (df.WKHP >= 35) & df.weeks40 & (df.PERNP > 5499)]

    print("\nPin: HC econ counts by year (unweighted / weighted), ours vs HC code comments")
    pin_ok = True
    for y in FOLDERS:
        g = s[s.YEAR == y]
        ours = (len(g), int(g.PWGTP.sum()))
        pin_ok &= ours == HC_ECON[y]
        print(f"  {y}: ours {ours}  HC {HC_ECON[y]}  {'EXACT' if ours == HC_ECON[y] else 'MISS'}")
    total = len(s)
    print(f"  total {total:,} (HC 8,775)")

    results = {k: check_table(s, k, total) for k in BLOCKS}
    print(f"\nPin {'PASS' if pin_ok else 'FAIL'}; Table 1 {'PASS' if results['table1'] else 'FAIL'}; "
          f"Table 2 {'PASS' if results['table2'] else 'FAIL'}; elapsed {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
