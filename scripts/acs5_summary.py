"""Step 8 report: hidden counts per panel and switch, label agreement for the variants, and the
cross-check. Reads data/current.json -> the bundle, and output/checks/acs5-variants.json.

Run from the repo root:  python3 scripts/acs5_summary.py
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ECON = "Economics"


def load(name):
    bid = json.loads((ROOT / "data/current.json").read_text())["bundle"]
    return json.loads((ROOT / "data/bundles" / bid / f"{name}.json").read_text())


def so_labels(so, which="major_top"):
    """{(major, occp): label} for one same-occupation setting."""
    out = {}
    for m, v in so.items():
        key = "econ_vs_all" if m == ECON else "econ_vs_major"
        for r in v[which]["rows"]:
            out[(m, r["occp"])] = r[key]["label"]
    return out


def agreement(a, b):
    both = [k for k in a if a[k] and b.get(k)]
    same = sum(a[k] == b[k] for k in both)
    return f"labeled in both {len(both)}; same label {same} ({100 * same / max(len(both), 1):.1f}%)"


def main():
    so, loc = load("same_occupation"), load("local")
    var = json.loads((ROOT / "output/checks/acs5-variants.json").read_text())
    man = json.loads((ROOT / "data/bundles" / json.loads((ROOT / "data/current.json").read_text())["bundle"]
                      / "manifest.json").read_text())
    print("bundle:", man["bundle"], "| gates:", json.dumps(man["gates"]))

    print("\n== Panel 3, same occupation (73 majors x 10 rows per list)")
    for k, s in so.items():
        for which in ("major_top", "economics_top"):
            labs = Counter(l for l in so_labels(s, which).values())
            reasons = Counter(r[g]["reason"] for v in s.values() for r in v[which]["rows"]
                              for g in ("economics", "major", "all") if g in r and r[g]["hidden"])
            print(f"  {k} {which}: labels {dict(labs)}; hidden cells by reason {dict(reasons)}")
    e = so["grad=0"][ECON]["major_top"]
    print("  economics top 10 (grad=0):", [(r["label"][:28], r["econ_vs_all"]["label"]) for r in e["rows"]])
    d0 = so_labels(so["grad=0"])
    print("  D4 check, ages 35-45 no reweighting vs default:", agreement(d0, so_labels(var["same_occupation_ages_35_45"])),
          "| hidden rows 35-45:", sum(v is None for v in so_labels(var["same_occupation_ages_35_45"]).values()),
          "vs default:", sum(v is None for v in d0.values()))
    print("  P1, earnings (PERNP) vs wages:", agreement(d0, so_labels(var["same_occupation_pernp"])))

    print("\n== Panel 5, local")
    for k, s in loc.items():
        for area, a in s.items():
            hid = sum(r["major"]["hidden"] for m, r in a["by_major"].items() if m != ECON)
            labs = Counter(r["econ_vs_major"]["label"] for m, r in a["by_major"].items() if m != ECON)
            print(f"  {k} {area}: econ n {a['economics']['n']} median {a['economics'].get('median')} "
                  f"hidden {a['economics']['hidden']} ({a['economics']['reason']}); all n {a['all']['n']}; "
                  f"majors hidden {hid}/72; econ vs major {dict(labs)}; econ vs all {a['econ_vs_all']['label']}")
    for name in ("local_ages_35_45", "local_pernp", "local_sf_with_08625"):
        for area, a in var[name].items():
            hid = sum(r["major"]["hidden"] for m, r in a["by_major"].items() if m != ECON)
            print(f"  variant {name} {area}: econ n {a['economics']['n']} median {a['economics'].get('median')} "
                  f"hidden {a['economics']['hidden']}; majors hidden {hid}/72")

    print("\n== Cross-check (warning only):", json.dumps(var["cross_check_econ_mid_pay"]))


if __name__ == "__main__":
    main()
