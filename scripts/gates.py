"""Step 9: the hard gates H1-H10 on a candidate bundle (spec/gates.yaml, written before this code).

Every gate reads only the candidate bundle, the live bundle (data/current.json), tracked spec/
files, and the files named on the command line (--dictionary-1y / --dictionary-5y for H8, --probe
for H9). Never raw/ or output/: the step-11 runner has neither.

Run from the repo root:
  python3 scripts/gates.py <bundle id> [--data data] [--live <id>] --dictionary-1y <csv> --dictionary-5y <csv> [--probe <json>]
Prints the report; exit 0 if every hard gate passes, 1 if any fails.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Z90 = 1.645
ECON = "Economics"
FILES = ["codes.json", "hc_tables_5yr.json", "local.json", "rank.json", "same_occupation.json"]
MAX_BYTES = 10 * 1024 * 1024
MICRODATA_KEY = re.compile(r"^(SERIALNO|SPORDER|PWGTP\d*)$")
RANK_MEASURES = 10
RATES = ("unemployment", "underemployment")
# H8: variables the builds read, reduced to their shape. ADJINC changes every year (D2); the
# code-list variables (FOD1P, FOD2P, OCCP, INDP, SOCP, PUMA) are H2's job; SERIALNO's codes hold years.
SHAPE_VARS = ["SERIALNO", "SPORDER", "STATE", "AGEP", "SCHL", "SCH", "ESR", "WKHP", "WKWN", "WAGP",
              "PERNP", "COW", "MIL", "SEX", "RELSHIPP", "PWGTP"]
NAME_ONLY = {"SERIALNO"}
GATES = ["H1_outputs", "H2_codes_mapped", "H3_majors_present", "H4_south_florida", "H5_cell_rules",
         "H6_labels", "H7_sample_size", "H8_dictionary", "H9_source_revision", "H10_provenance"]


# ---------- loading ----------

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def live_id(data):
    p = Path(data) / "current.json"
    return json.loads(p.read_text())["bundle"] if p.exists() else None


def load_bundle(data, bid):
    """{file name: parsed JSON} for one bundle, plus 'manifest'; a file that fails to parse -> None."""
    d = Path(data) / "bundles" / bid
    out = {}
    for name in ["manifest.json"] + FILES:
        try:
            out[name[:-5]] = json.loads((d / name).read_text())
        except (OSError, ValueError):
            out[name[:-5]] = None
    return out


def dictionary_shape(path):
    """A PUMS data dictionary reduced to what the gate compares (spec H8)."""
    shape, reps = {}, set()
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.reader(fh):
            if len(r) < 4:
                continue
            kind, var = r[0], r[1]
            if re.fullmatch(r"PWGTP\d+", var):
                reps.add(var)
                continue
            if var not in SHAPE_VARS:
                continue
            s = shape.setdefault(var, {"name": set(), "codes": set()})
            if kind == "NAME":
                s["name"].add((r[2], r[3]))
            elif kind == "VAL" and var not in NAME_ONLY and len(r) >= 6:
                if r[2] == "C" or r[4] == r[5]:          # categorical: all codes; numeric: special codes only
                    s["codes"].add((r[4], r[5]))
    out = {v: {"name": sorted(map(list, s["name"])), "codes": sorted(map(list, s["codes"]))}
           for v, s in sorted(shape.items())}
    out["_missing"] = sorted(set(SHAPE_VARS) - set(shape))
    out["_replicate_weights"] = len(reps)
    return out


# ---------- walking cells ----------

def walk(obj, path=""):
    """Yield (path, dict) for every dict in a JSON tree."""
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from walk(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0


def moe_ok(c):
    return finite(c.get("se")) and finite(c.get("moe")) and abs(c["moe"] - Z90 * c["se"]) <= 1e-3 * c["moe"] + 1e-6


def expected_label(d, moe):
    """C3 label; None when d sits inside rounding of the boundary (either label accepted)."""
    if abs(abs(d) - moe) < 0.02:
        return None
    return "better" if d > moe else "worse" if d < -moe else "about the same"


# ---------- the gates (each returns a list of problems; empty = pass) ----------

def h1_outputs(data, bid, b):
    bad, d = [], Path(data) / "bundles" / bid
    m = b["manifest"]
    if m is None:
        return ["manifest.json missing or not JSON"]
    if sorted(m.get("files", {})) != FILES:
        bad.append(f"manifest lists {sorted(m.get('files', {}))}, expected {FILES}")
    for name in FILES:
        p = d / name
        if b[name[:-5]] is None:
            bad.append(f"{name} missing or not JSON")
            continue
        if p.stat().st_size > MAX_BYTES:
            bad.append(f"{name} is {p.stat().st_size:,} bytes (> 10 MB)")
        if sha(p) != m.get("files", {}).get(name):
            bad.append(f"{name} sha256 differs from the manifest")
        keys = {k for _, o in walk(b[name[:-5]]) for k in o if MICRODATA_KEY.match(str(k))}
        if keys:
            bad.append(f"{name} holds microdata keys {sorted(keys)}")
    r = b["rank"]
    if r is not None:
        ms = r.get("measures", {})
        if len(ms) != RANK_MEASURES or any(len(v) != 73 for v in ms.values()):
            bad.append(f"rank: {len(ms)} measures, rows {sorted({len(v) for v in ms.values()})} (want 10 x 73)")
    return bad


def h2_codes_mapped(b):
    m, bad = b["manifest"], []
    g, s1 = m.get("gates", {}), m.get("stats", {}).get("acs1", {})
    for k in ("occp_without_label", "indp_unmapped", "hc_table2_indp_unmapped"):
        if g.get(k) != []:
            bad.append(f"5-year {k} = {g.get(k)}")
    if g.get("fod1p_unmapped_persons") != 0:
        bad.append(f"5-year fod1p_unmapped_persons = {g.get('fod1p_unmapped_persons')}")
    if s1.get("fod1p_unmapped_persons") != 0:
        bad.append(f"1-year fod1p_unmapped_persons = {s1.get('fod1p_unmapped_persons')}")
    emp, uns = s1.get("civilian_employed_recent_grads"), s1.get("civilian_employed_recent_grads_unscored")
    if not emp or uns is None or uns / emp >= 0.001:
        bad.append(f"1-year civilian jobs with no O*NET score: {uns} of {emp} (rule < 0.1%)")
    return bad


def h3_majors_present(b):
    bad = []
    for k, v in (b["same_occupation"] or {}).items():
        if len(v) != 73:
            bad.append(f"same_occupation {k}: {len(v)} majors")
    t3 = (b["hc_tables_5yr"] or {}).get("table3", {}).get("rows", [])
    if sum(r.get("frequency", 0) > 0 for r in t3) != 73:
        bad.append(f"hc table3: {sum(r.get('frequency', 0) > 0 for r in t3)} majors present")
    for k, rows in ((b["rank"] or {}).get("measures", {})).items():
        if len({r["major"] for r in rows}) != 73:
            bad.append(f"rank {k}: {len({r['major'] for r in rows})} majors")
    return bad


def h4_south_florida(b, live):
    new = (b["codes"] or {}).get("south_florida_pumas")
    if not new:
        return ["codes.json has no South Florida PUMA list"]
    if live is None or live.get("codes") is None:
        return []                                        # first bundle with a list: nothing to compare
    old = live["codes"].get("south_florida_pumas")
    if new != old:
        return [f"South Florida PUMA list changed: dropped {sorted(set(old) - set(new))}, "
                f"added {sorted(set(new) - set(old))} (G1 needs a new reading)"]
    return []


def h5_cell_rules(b):
    bad = []
    for name in ("same_occupation", "local", "hc_tables_5yr"):
        for path, c in walk(b[name] or {}):
            where = f"{name}{path}"
            if "hidden" in c and "n" in c:                       # a pay cell (median or age-mix hidden)
                if c["hidden"]:
                    if not c.get("reason"):
                        bad.append(f"{where}: hidden with no reason")
                    if "se" in c and not moe_ok(c):
                        bad.append(f"{where}: se/moe invalid")
                else:
                    if not moe_ok(c) or not finite(c.get("median")):
                        bad.append(f"{where}: shown with invalid median/se/moe")
                    elif c["n"] < 100 or c["moe"] / c["median"] > 0.30:
                        bad.append(f"{where}: shown but fails D5 (n {c['n']}, moe/est {c['moe'] / c['median']:.3f})")
            elif "share" in c or "d" in c:                        # a share or a difference
                if not moe_ok(c):
                    bad.append(f"{where}: se/moe invalid")
    for k, rows in ((b["rank"] or {}).get("measures", {})).items():
        for r in rows:
            where = f"rank {k} {r['major']}"
            if not finite(r.get("se")):
                bad.append(f"{where}: se invalid")
            elif k in RATES:
                if r["n"] < 100 and not r["hidden"]:
                    bad.append(f"{where}: n {r['n']} < 100 but shown")
            elif r["hidden"] != (r["n"] < 100 or r["moe_ratio"] > 0.30):
                bad.append(f"{where}: hidden = {r['hidden']} but n {r['n']}, moe_ratio {r['moe_ratio']}")
    return bad


def check_label(where, diff, sides, bad):
    hidden = any(s is None or s.get("hidden", True) for s in sides)
    lab = diff.get("label")
    if hidden != (lab is None):
        bad.append(f"{where}: label {lab!r} but a side hidden = {hidden}")
    elif lab is not None:
        want = expected_label(diff["d"], diff["moe"])
        if want is not None and lab != want:
            bad.append(f"{where}: label {lab!r}, rule gives {want!r} (d {diff['d']}, moe {diff['moe']})")
    return lab


def h6_labels(b):
    bad = []
    for k, majors in (b["same_occupation"] or {}).items():
        for m, v in majors.items():
            for which in ("major_top", "economics_top"):
                t = v[which]
                counts, hidden_rows = {"better": 0, "about the same": 0, "worse": 0}, 0
                for r in t["rows"]:
                    labs = {}
                    for key, other in (("econ_vs_major", "major"), ("econ_vs_all", "all")):
                        if key in r:
                            labs[key] = check_label(f"same_occupation {k} {m} {which} {r['occp']} {key}",
                                                    r[key], [r.get("economics"), r.get(other)], bad)
                    lab = labs.get("econ_vs_all" if m == ECON else "econ_vs_major")
                    if lab is None:
                        hidden_rows += 1
                    else:
                        counts[lab] += 1
                if t["headline"] != counts or t["hidden_rows"] != hidden_rows:
                    bad.append(f"same_occupation {k} {m} {which}: headline {t['headline']} / hidden "
                               f"{t['hidden_rows']}, rows give {counts} / {hidden_rows}")
    for k, areas in (b["local"] or {}).items():
        for area, a in areas.items():
            check_label(f"local {k} {area} econ_vs_all", a["econ_vs_all"], [a["economics"], a["all"]], bad)
            for m, r in a["by_major"].items():
                if "econ_vs_major" in r and m != ECON:           # economics vs itself has no label
                    check_label(f"local {k} {area} {m}", r["econ_vs_major"], [a["economics"], r.get("major")], bad)
    return bad


def h7_sample_size(b, live):
    if live is None or not live["manifest"].get("stats"):
        return []                                        # first bundle with stats: nothing to compare
    bad, new, old = [], b["manifest"].get("stats", {}), live["manifest"]["stats"]
    for src in ("acs1", "acs5"):
        for k in ("records_kept", "pwgtp_sum"):
            o, n = old.get(src, {}).get(k), new.get(src, {}).get(k)
            if not o or n is None or abs(n / o - 1) > 0.05:
                bad.append(f"{src} {k}: {o} -> {n} (rule within 5%)")
    return bad


def h8_dictionary(d1, d5):
    base = json.loads((ROOT / "spec" / "dictionary-baseline.json").read_text())
    bad = []
    for src, path in (("acs1", d1), ("acs5", d5)):
        if not path:
            bad.append(f"{src}: no data dictionary given (no silent skip)")
            continue
        got, want = dictionary_shape(path), base[src]
        for v in sorted(set(got) | set(want)):
            if got.get(v) != want.get(v):
                bad.append(f"{src} {v}: dictionary shape changed: {want.get(v)} -> {got.get(v)}")
    return bad


def h9_source_revision(probe, live):
    """Notes are returned in a second list; problems hold the publish."""
    if not probe:
        return [], ["no probe file: not run (local build)"]
    if live is None:
        return [], ["first bundle: no published source to compare"]
    stored = json.loads((ROOT / "spec" / "sources.json").read_text())
    got = json.loads(Path(probe).read_text()).get("sources", {})
    bad = []
    for path in live["manifest"].get("sources", {}):
        sid = Path(path).parent.name                     # raw/acs5-2020-2024/csv_pus.zip -> acs5-2020-2024
        s, p = stored.get(sid), got.get(sid)
        if s is None:
            bad.append(f"{sid}: not in spec/sources.json")
        elif p is None:
            bad.append(f"{sid}: the probe did not check it")
        elif p.get("sha256") and p["sha256"] != s["sha256"]:
            bad.append(f"{sid}: sha256 {s['sha256'][:12]} -> {p['sha256'][:12]}")
        elif not p.get("sha256") and (p.get("bytes") != s["bytes"] or p.get("last_modified") != s["last_modified"]):
            bad.append(f"{sid}: bytes / Last-Modified {s['bytes']} {s['last_modified']!r} -> "
                       f"{p.get('bytes')} {p.get('last_modified')!r}")
    return bad, []


def h10_provenance(b):
    m, bad = b["manifest"], []
    if not re.fullmatch(r"[0-9a-f]{40}", str(m.get("git_commit", ""))):
        bad.append(f"git_commit {m.get('git_commit')!r} is not a commit id")
    if m.get("worktree_dirty") is not False:
        bad.append(f"worktree_dirty = {m.get('worktree_dirty')!r} (build from a clean tree)")
    return bad


def run(data, bid, live_bid=None, dictionary_1y=None, dictionary_5y=None, probe=None):
    """All hard gates. Returns {candidate, live, passed, gates: {id: {ok, problems, notes}}}."""
    b = load_bundle(data, bid)
    live_bid = live_bid if live_bid is not None else live_id(data)
    live = load_bundle(data, live_bid) if live_bid else None
    res = {}
    h1 = h1_outputs(data, bid, b)
    res["H1_outputs"] = (h1, [])
    if b["manifest"] is None or any(b[n[:-5]] is None for n in FILES):
        for g in GATES[1:]:                              # nothing else can be read
            res[g] = (["not run: H1 failed"], [])
    else:
        notes4 = ["first bundle with a PUMA list"] if live is None or live.get("codes") is None else []
        notes7 = ["first bundle with stats"] if live is None or not live["manifest"].get("stats") else []
        res["H2_codes_mapped"] = (h2_codes_mapped(b), [])
        res["H3_majors_present"] = (h3_majors_present(b), [])
        res["H4_south_florida"] = (h4_south_florida(b, live), notes4)
        res["H5_cell_rules"] = (h5_cell_rules(b), [])
        res["H6_labels"] = (h6_labels(b), [])
        res["H7_sample_size"] = (h7_sample_size(b, live), notes7)
        res["H8_dictionary"] = (h8_dictionary(dictionary_1y, dictionary_5y), [])
        res["H9_source_revision"] = h9_source_revision(probe, live)
        res["H10_provenance"] = (h10_provenance(b), [])
    gates = {g: {"ok": not res[g][0], "problems": res[g][0], "notes": res[g][1]} for g in GATES}
    return {"candidate": bid, "live": live_bid, "passed": all(v["ok"] for v in gates.values()), "gates": gates}


def summary(report, limit=5):
    lines = [f"candidate {report['candidate']} | live {report['live']} | "
             f"{'PASS' if report['passed'] else 'HOLD'}"]
    for g, v in report["gates"].items():
        extra = "; ".join(v["problems"][:limit]) + (f" (+{len(v['problems']) - limit} more)" if len(v["problems"]) > limit else "")
        lines.append(f"  {g:<20} {'pass' if v['ok'] else 'FAIL'}  {extra}{'; '.join(v['notes'])}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--live", default=None, help="live bundle id (default: data/current.json)")
    ap.add_argument("--dictionary-1y")
    ap.add_argument("--dictionary-5y")
    ap.add_argument("--probe")
    a = ap.parse_args(argv)
    rep = run(a.data, a.bundle, a.live, a.dictionary_1y, a.dictionary_5y, a.probe)
    print(summary(rep))
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
