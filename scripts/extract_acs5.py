"""Step 8: one pass over the 2020-24 5-year national person files -> a filtered cache extract.

Keeps bachelor's-or-higher people aged 22-65 (every step-8 panel draws from them) with the
columns the panels use, and the 80 replicate weights. Prints a profile by survey year
(SERIALNO starts with the year): records, ADJINC values, and the OCCP / INDP code sets,
so the code-set rule is read from the file, not assumed. In the same pass it sums PWGTP and
PWGTP1-80 by state for the person rows of the Census verification file (all persons), and
counts records per CSV part, for the fixture test (scripts/acs5_fixture.py).

Run from the repo root:  python3 scripts/extract_acs5.py
Reads raw/acs5-2020-2024/csv_pus.zip (read-only); writes cache/acs5-2020-2024-ba.parquet
(disposable; gitignored), output/checks/acs5-profile.json, and output/checks/acs5-fixture-sums.csv.
"""
import csv
import json
import time
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / "raw" / "acs5-2020-2024" / "csv_pus.zip"
OUT = ROOT / "cache" / "acs5-2020-2024-ba.parquet"
REPS = [f"PWGTP{i}" for i in range(1, 81)]
COLS = ["SERIALNO", "SPORDER", "STATE", "PUMA", "ADJINC", "AGEP", "SCHL", "SCH", "ESR", "WKHP",
        "WKWN", "WAGP", "PERNP", "COW", "FOD1P", "FOD2P", "OCCP", "INDP", "MIL", "SEX", "RELSHIPP",
        "PWGTP"] + REPS
DTYPES = {"SERIALNO": str, "OCCP": str, "INDP": str, "FOD1P": "Int64", "FOD2P": "Int64",
          "PUMA": str, "STATE": str}
AGES = [(0, 4), (5, 9), (10, 14), (15, 19), (20, 24), (25, 34), (35, 44), (45, 54), (55, 59), (60, 64),
        (65, 74), (75, 84), (85, 200)]


def fixture_rows(c):
    """Person rows of pums_estimates_20_24.csv, as masks on one chunk (names as Census prints them)."""
    rows = {"Total population": c.AGEP >= 0,
            "Housing unit population (RELSHIPP=20-36)": c.RELSHIPP.between(20, 36),
            "GQ population (RELSHIPP=37-38)": c.RELSHIPP.between(37, 38),
            "GQ institutional population (RELSHIPP=37)": c.RELSHIPP == 37,
            "GQ noninstitutional population (RELSHIPP=38)": c.RELSHIPP == 38,
            "Total males (SEX=1)": c.SEX == 1, "Total females (SEX=2)": c.SEX == 2}
    for lo, hi in AGES:
        rows[f"Age {lo}-{hi}" if hi < 200 else "Age 85 and over"] = c.AGEP.between(lo, hi)
    return rows


def main():
    t0 = time.time()
    z = zipfile.ZipFile(ZIP)
    parts, n_all, n_file, sums = [], {}, {}, {}
    for name in sorted(n for n in z.namelist() if n.startswith("psam_pus") and n.endswith(".csv")):
        with z.open(name) as fh:
            for chunk in pd.read_csv(fh, usecols=COLS, chunksize=500_000, dtype=DTYPES):
                yr = chunk.SERIALNO.str[:4]
                for y, k in yr.value_counts().items():
                    n_all[y] = n_all.get(y, 0) + int(k)
                n_file[name] = n_file.get(name, 0) + len(chunk)
                for row, m in fixture_rows(chunk).items():
                    for st, s in chunk.loc[m, ["PWGTP"] + REPS].groupby(chunk.STATE[m]).sum().iterrows():
                        acc = sums.setdefault((st, row), [0] * 81)
                        sums[(st, row)] = [a + int(b) for a, b in zip(acc, s.tolist())]
                parts.append(chunk[(chunk.SCHL >= 21) & chunk.AGEP.between(22, 65)])
        print(f"  read {name}: {sum(len(p) for p in parts):,} kept so far, {time.time() - t0:.0f} s", flush=True)
    df = pd.concat(parts, ignore_index=True).sort_values(["SERIALNO", "SPORDER"], kind="mergesort")
    df["YEAR"] = df.SERIALNO.str[:4].astype(int)
    for c in REPS + ["PWGTP"]:
        df[c] = df[c].astype("int32")
    OUT.parent.mkdir(exist_ok=True)
    df.to_parquet(OUT, index=False)

    # Profile by survey year: what the panels' code rules must handle
    prof = {"records_all_persons": dict(sorted(n_all.items())), "kept_ba_plus_22_65": {},
            "adjinc": {}, "occp_codes": {}, "indp_codes": {}, "negative_replicate_weights": int((df[REPS] < 0).sum().sum())}
    for y, g in df.groupby("YEAR"):
        prof["kept_ba_plus_22_65"][y] = len(g)
        prof["adjinc"][y] = sorted(g.ADJINC.unique().tolist())
        prof["occp_codes"][y] = sorted(g.OCCP.dropna().unique().tolist())
        prof["indp_codes"][y] = sorted(g.INDP.dropna().unique().tolist())
    prof["records_by_file"] = n_file
    (ROOT / "output" / "checks" / "acs5-profile.json").write_text(json.dumps(prof, indent=1, default=str))
    with (ROOT / "output" / "checks" / "acs5-fixture-sums.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["STATE", "CHARACTERISTIC", "PWGTP"] + REPS)
        for (st, row), v in sorted(sums.items()):
            w.writerow([st, row] + v)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(df):,} rows; {time.time() - t0:.0f} s")
    for y in prof["adjinc"]:
        print(f"  {y}: {prof['kept_ba_plus_22_65'][y]:,} kept; ADJINC {prof['adjinc'][y]}; "
              f"{len(prof['occp_codes'][y])} OCCP codes; {len(prof['indp_codes'][y])} INDP codes")
    print("  negative replicate weights:", prof["negative_replicate_weights"])


if __name__ == "__main__":
    main()
