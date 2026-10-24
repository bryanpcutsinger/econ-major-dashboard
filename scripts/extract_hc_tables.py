"""Extract Holian and Chiu (2026) Tables 1-3 from the PDF (no retyping).

Runs `pdftotext -layout` on the PDF, reads each table's rows (columns are
separated by two or more spaces), and checks the row counts: Table 1 = 40,
Table 2 = 20, Table 3 = 73.

Usage:  python3 scripts/extract_hc_tables.py <path-to-pdf>
Writes raw/benchmarks/hc-2026/table{1,2,3}.csv and appends to raw/benchmarks/PROVENANCE.csv.
"""
import csv
import datetime as dt
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "raw" / "benchmarks" / "hc-2026"

TABLES = {
    # name: (title prefix, column names, expected rows, number of numeric columns)
    "table1": ("Table 1. Popular occupations", ["occupation", "frequency", "pct_of_majors", "median_income"], 40, 3),
    "table2": ("Table 2. Popular industries", ["industry", "frequency", "pct_of_majors", "median_income"], 20, 3),
    "table3": ("Table 3. Median income", ["major", "frequency", "pct_of_sample", "median_income",
                                          "self_employment_rate"], 73, 4),
}
NUM = re.compile(r"^\d+(\.\d+)?$")


def rows_after(lines, title, nnum):
    """Collect table rows from the title line until 'Notes:'; follow 'Continued' pages."""
    out, pending, inside = [], "", False
    for line in lines:
        s = line.replace("\u2002", " ").strip()  # the PDF puts an en space after "Table N."
        if s.startswith(title) or (inside is None and s.startswith(title.split(".")[0] + ". Continued")):
            inside = True
            continue
        if not inside:
            continue
        if s.startswith("Notes:"):
            inside = None  # paused: a "Continued" page may follow
            continue
        if s.startswith("(Continued)"):
            inside = None
            continue
        parts = re.split(r"\s{2,}", s)
        nums = [p for p in parts[1:] if NUM.match(p)]
        if len(parts) >= nnum + 1 and len(nums) == nnum and NUM.match(parts[-1]):
            name = (pending + " " + parts[0]).strip()
            out.append([name] + parts[-nnum:])
            pending = ""
        elif s and line.startswith("    ") and out and len(parts) == 1:
            out[-1][0] += " " + s  # an indented line continues the previous row's name
        elif s and not s[0].isdigit() and not s.lower().startswith(("occupation", "industry", "major")):
            pending = (pending + " " + s).strip()  # a name printed above its numbers
    return out


def main(pdf_path):
    text = subprocess.run(["pdftotext", "-layout", pdf_path, "-"], check=True,
                          capture_output=True, text=True).stdout
    lines = text.splitlines()
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, (title, header, expected, nnum) in TABLES.items():
        rows = rows_after(lines, title, nnum)
        share = sum(float(r[2]) for r in rows)
        print(f"{name}: {len(rows)} rows (expected {expected}); share column sums to {share:.1f}")
        ok &= len(rows) == expected
        with (OUT / f"{name}.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)

    sha = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (ROOT / "raw" / "benchmarks" / "PROVENANCE.csv").open("a", newline="") as fh:
        csv.writer(fh).writerow(
            ["hc-2026/table{1,2,3}.csv",
             "Holian & Chiu (2026) J Econ Educ 57(3), pdftotext -layout of the Zotero PDF (XYRAITJR)",
             now, "", "pdf sha256 " + sha])
    if not ok:
        sys.exit("Row counts do not match: inspect the PDF text before using these tables.")


if __name__ == "__main__":
    main(sys.argv[1])
