"""Step 9: write the tracked baselines the gates compare against (spec/gates.yaml inputs).

  spec/sources.json             url, bytes, Last-Modified, sha256 of each published source zip and its
                                data dictionary (H9), copied from the raw/ provenance records
  spec/dictionary-baseline.json the shape of each data dictionary (H8), from scripts/gates.py

Run from the repo root once per published vintage:  python3 scripts/make_baselines.py
Reads raw/ (read-only); writes only the two spec files.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from gates import dictionary_shape  # noqa: E402

# source id (= the raw/ folder) -> its frozen data dictionary
SOURCES = {"acs1-2024": "census-1yr/PUMS_Data_Dictionary_2024.csv",
           "acs5-2020-2024": "census-5yr/PUMS_Data_Dictionary_2020-2024.csv"}


def provenance(path):
    """key: value lines of a raw/<source>/PROVENANCE.txt."""
    out = {}
    for line in path.read_text().splitlines():
        k, _, v = line.partition(": ")
        out[k] = v
    return out


def main():
    frozen = {r["file"]: r for r in csv.DictReader(open(ROOT / "raw/benchmarks/PROVENANCE.csv"))}
    sources, shapes = {}, {}
    for sid, dict_file in SOURCES.items():
        p = provenance(ROOT / "raw" / sid / "PROVENANCE.txt")
        d = frozen[dict_file]
        sources[sid] = {"url": p["source"], "bytes": int(p["bytes"]), "last_modified": p["last_modified_header"],
                        "sha256": p["sha256"], "accessed": p["accessed"],
                        "dictionary": {"url": d["source_url"], "bytes": int(d["bytes"]), "sha256": d["sha256"],
                                       "accessed": d["accessed_utc"]}}
        shapes[sid.split("-")[0]] = dictionary_shape(ROOT / "raw/benchmarks" / dict_file)
    for name, obj in (("sources.json", sources), ("dictionary-baseline.json", shapes)):
        (ROOT / "spec" / name).write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
        print("wrote spec/" + name)
    for src, s in shapes.items():
        print(f"  {src}: {len(s) - 2} variables, {s['_replicate_weights']} replicate weights, missing {s['_missing']}")


if __name__ == "__main__":
    main()
