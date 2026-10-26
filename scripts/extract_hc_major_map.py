"""Extract the authors' 73-major map from the Holian-Chiu replication code.

Source: OpenICPSR 241262 V1, script_jobs_majors_20251210.R, lines 1227-1413
(`ACS_majors$major2=recode(ACS_majors$DEGFIELDD, ...)`). HC say these are the
Abel-Deitz (NY Fed) codes, plus 1107 and 4009 for 2023 (script line 1225).
IPUMS DEGFIELDD uses the Census field-of-degree codes, so the map applies to
FOD1P directly. car::recode leaves an unlisted code as its own number, so an
unlisted code never joins one of the 73 groups.

Run from the repo root:  python3 scripts/extract_hc_major_map.py
Reads raw/benchmarks/ (read-only); writes raw/benchmarks/hc-2026-openicpsr/derived/major73-hc.csv and prints a
comparison with spec/major73.csv (our pre-code map), the NY Fed names, and the
Census code lists.
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw" / "benchmarks"
SCRIPT = RAW / "hc-2026-openicpsr" / "ICPSR_241262-V1.0" / "script_jobs_majors_20251210.R"
YEARS = [2018, 2019, 2021, 2022, 2023, 2024]
# HC spelling -> NY Fed spelling (same groups; the published file uses "&")
SPELLING = {
    "Commercial Art and Graphic Design": "Commercial Art & Graphic Design",
    "Information Systems and Management": "Information Systems & Management",
    "Miscellaneous Biological Sciences": "Miscellaneous Biological Science",
}


def hc_map():
    """{code: (major, R line number)} from the major2 recode block."""
    lines = SCRIPT.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if "major2=recode(ACS_majors$DEGFIELDD" in l)
    out = {}
    for i in range(start, len(lines)):
        for code, name in re.findall(r"(\d+)\s*=\s*'([^']*)'", lines[i]):
            assert int(code) not in out, f"duplicate code {code}"
            name = " ".join(name.split())  # the labels carry tabs
            out[int(code)] = (SPELLING.get(name, name), i + 1)
        if lines[i].rstrip().endswith('")'):
            break
    return out


def census_codes():
    """{code: (label, years present)} from the frozen FOD1P code lists."""
    out = {}
    for y in YEARS:
        meta = json.loads((RAW / "census-codelists" / f"FOD1P-{y}.json").read_text())
        items = meta["values"]["item"]
        for k, label in items.items():
            if k.strip().isdigit() and int(k) > 0:
                out.setdefault(int(k), [label, []])[1].append(y)
    return out


def main():
    hc = hc_map()
    census = census_codes()
    ours = {int(r["fod1p"]): r for r in csv.DictReader(open(ROOT / "spec" / "major73.csv"))}
    nyfed = {r["Major"] for r in csv.DictReader(
        open(RAW / "nyfed-2024" / "college-labor-outcomes-by-major-data.csv", encoding="utf-8-sig"))} - {"Overall"}

    with (ROOT / "raw/benchmarks/hc-2026-openicpsr/derived/major73-hc.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fod1p", "census_label", "nyfed_major", "r_line", "in_census_lists", "ours_before"])
        for code in sorted(set(hc) | set(census)):
            major, line = hc.get(code, ("", ""))
            label, years = census.get(code, ("", []))
            w.writerow([code, label, major, line, "-".join(map(str, [min(years), max(years)])) if years else "",
                        ours.get(code, {}).get("nyfed_major", "")])

    groups = {m for m, _ in hc.values()} - {"N/A"}
    print(f"HC map: {len(hc)} codes, {len(groups)} groups")
    print("  groups not among the NY Fed 73 names:", sorted(groups - nyfed))
    print("  NY Fed names with no HC code:", sorted(nyfed - groups))
    print("Census codes (any year) not in the HC map:",
          [(c, census[c][0], census[c][1]) for c in sorted(set(census) - set(hc))])
    print("HC codes not in any Census list:", sorted(set(hc) - set(census) - {0}))
    diffs = [(c, ours[c]["census_label"], ours[c]["nyfed_major"], hc[c][0], ours[c]["basis"])
             for c in sorted(set(ours) & set(hc)) if ours[c]["nyfed_major"] != hc[c][0]]
    print(f"\nCodes where our pre-code map differs from HC: {len(diffs)}")
    for d in diffs:
        print("  ", d)


if __name__ == "__main__":
    main()
