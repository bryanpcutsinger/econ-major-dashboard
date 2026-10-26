"""Step 9: the change list, candidate bundle vs live bundle, and warnings W1-W6 (spec/gates.yaml).

Warnings never hold a publish (C2 auto-publish); they go into the new-data issue. Values are compared
as published: each bundle's dollar year is printed, and no extra deflator is applied (D2).

Run from the repo root:  python3 scripts/change_list.py <bundle id> [--data data] [--live <id>]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from gates import ECON, RATES, Z90, live_id, load_bundle  # noqa: E402

TWO_STEP = {("better", "worse"), ("worse", "better")}


def flatten(b):
    """{key: number record}, {key: label}, {key: rank} for one bundle. Each number record names its
    panel and setting in 'group' (used for W6)."""
    nums, labels, ranks = {}, {}, {}

    def num(key, c, kind, econ, group):
        nums[key] = {"value": c.get("median"), "moe": c.get("moe"), "hidden": bool(c.get("hidden")),
                     "kind": kind, "econ": econ, "group": group}

    for k, rows in b["rank"]["measures"].items():
        kind = "rate" if k in RATES else "pay"
        for r in rows:
            key = f"rank|{k}|{r['major']}"
            nums[key] = {"value": r["estimate"], "moe": Z90 * r["se"], "hidden": r["hidden"], "kind": kind,
                         "econ": r["major"] == ECON, "group": f"rank|{k}"}
            ranks[key] = r["rank"]
    for k, majors in b["same_occupation"].items():
        for m, v in majors.items():
            for which in ("major_top", "economics_top"):
                for r in v[which]["rows"]:
                    base = f"same_occupation|{k}|{m}|{which}|{r['occp']}"
                    for grp in ("economics", "major", "all"):
                        if grp in r:
                            num(f"{base}|{grp}", r[grp], "pay", grp == "economics", f"same_occupation|{k}")
                    for lk in ("econ_vs_major", "econ_vs_all"):
                        if lk in r:
                            labels[f"{base}|{lk}"] = r[lk].get("label")
    for k, areas in b["local"].items():
        for area, a in areas.items():
            base = f"local|{k}|{area}"
            num(f"{base}|economics", a["economics"], "pay", True, f"local|{k}")
            num(f"{base}|all", a["all"], "pay", False, f"local|{k}")
            labels[f"{base}|econ_vs_all"] = a["econ_vs_all"].get("label")
            for m, r in a["by_major"].items():
                num(f"{base}|major|{m}", r["major"], "pay", m == ECON, f"local|{k}")
                if m != ECON:
                    labels[f"{base}|{m}|econ_vs_major"] = r["econ_vs_major"].get("label")
    for r in b["hc_tables_5yr"]["table3"]["rows"]:                # audit file: listed, never warned
        num(f"hc_tables_5yr|table3|{r['major']}", r["median"], "audit", r["major"] == ECON, "hc_tables_5yr|table3")
    return nums, labels, ranks


def econ_cell(key):
    """One id per economics cell: the same-occupation economics cell for a job and setting repeats in
    many majors' lists, and local by_major 'Economics' repeats the area's economics cell."""
    p = key.split("|")
    if p[0] == "same_occupation":                            # same_occupation|k|major|list|occp|economics
        return f"same_occupation|{p[1]}|{p[4]}"
    if p[0] == "local" and p[-2:] == ["major", ECON]:
        return "|".join(p[:3] + ["economics"])
    return key


def rel(old, new):
    return (new - old) / old if old else float("inf")


def build(data, bid, live_bid=None, pin_path=None):
    b = load_bundle(data, bid)
    live_bid = live_bid if live_bid is not None else live_id(data)
    out = {"candidate": bid, "live": live_bid, "years": {"new": b["manifest"].get("years")},
           "dollars": {"new": [b["manifest"].get("dollars"), b["rank"]["meta"].get("dollars")]}}
    pin = Path(pin_path) if pin_path else Path(data) / "lecture-pin.json"
    if not live_bid:
        out.update(first=True, warnings={}, numbers=[], label_flips=[], rank_moves=[], added=[], dropped=[],
                   newly_hidden=[], newly_shown=[], new_codes={}, pin="no lecture pin" if not pin.exists() else "")
        out["announcement"] = announcement(out)
        return out
    live = load_bundle(data, live_bid)
    out["first"] = False
    out["years"]["old"] = live["manifest"].get("years")
    out["dollars"]["old"] = [live["manifest"].get("dollars"), live["rank"]["meta"].get("dollars")]
    n_new, l_new, r_new = flatten(b)
    n_old, l_old, r_old = flatten(live)

    numbers, w, seen_econ = [], {f"W{i}": [] for i in range(1, 7)}, set()
    for key in sorted(set(n_new) & set(n_old)):
        o, n = n_old[key], n_new[key]
        if o["value"] is None or n["value"] is None:
            continue
        d = n["value"] - o["value"]
        rec = {"key": key, "old": o["value"], "new": n["value"], "diff": round(d, 4),
               "moe_old": o["moe"], "moe_new": n["moe"], "rel": round(rel(o["value"], n["value"]), 5)}
        numbers.append(rec)
        if o["hidden"] or n["hidden"]:
            continue
        if n["kind"] == "pay" and n["econ"] and abs(rec["rel"]) > 0.08:
            if econ_cell(key) not in seen_econ:              # one economics cell, counted once
                seen_econ.add(econ_cell(key))
                w["W1"].append(rec)
        elif n["kind"] == "pay" and not n["econ"] and abs(rec["rel"]) > 0.15 and abs(d) > (o["moe"] or 0) + (n["moe"] or 0):
            w["W2"].append(rec)
        elif n["kind"] == "rate" and abs(d) > 2:
            w["W3"].append(rec)
    moves = [{"key": k, "old": r_old[k], "new": r_new[k]} for k in sorted(set(r_new) & set(r_old))
             if abs(r_new[k] - r_old[k]) >= 5]
    w["W4"] = [m for m in moves if m["key"].endswith(f"|{ECON}")]
    flips = [{"key": k, "old": l_old[k], "new": l_new[k]} for k in sorted(set(l_new) & set(l_old))
             if l_old[k] != l_new[k]]
    w["W5"] = [f for f in flips if (f["old"], f["new"]) in TWO_STEP]
    for grp in sorted({v["group"] for v in n_new.values()}):
        keys = [k for k, v in n_new.items() if v["group"] == grp]
        h_new = sum(n_new[k]["hidden"] for k in keys)
        h_old = sum(v["hidden"] for v in n_old.values() if v["group"] == grp)
        if abs(h_new - h_old) > 0.10 * len(keys):
            w["W6"].append({"panel": grp, "hidden_old": h_old, "hidden_new": h_new, "cells": len(keys)})

    nc, oc = b["codes"] or {}, live["codes"] or {}
    new_codes = {}
    for src in ("acs5", "acs1"):
        for var, codes in (nc.get(src) or {}).items():
            added = sorted(set(map(str, codes)) - set(map(str, (oc.get(src) or {}).get(var, []))))
            if added and oc:
                new_codes[f"{src} {var}"] = added
    numbers.sort(key=lambda r: -abs(r["rel"]))
    out.update(warnings=w, numbers=numbers, label_flips=flips, rank_moves=moves,
               added=sorted(set(n_new) - set(n_old)), dropped=sorted(set(n_old) - set(n_new)),
               newly_hidden=sorted(k for k in set(n_new) & set(n_old) if n_new[k]["hidden"] and not n_old[k]["hidden"]),
               newly_shown=sorted(k for k in set(n_new) & set(n_old) if n_old[k]["hidden"] and not n_new[k]["hidden"]),
               new_codes=new_codes, pin=pin_note(data, pin, bid, l_new))
    out["announcement"] = announcement(out)
    return out


def pin_note(data, pin, bid, l_new):
    """Difference vs the lecture pin (step 12). No pin yet -> say so and go on."""
    if not pin.exists():
        return "no lecture pin"
    pinned = json.loads(pin.read_text()).get("bundle")
    if pinned == bid:
        return f"the lecture is pinned to this bundle ({bid})"
    pb = load_bundle(data, pinned)
    if pb["manifest"] is None:
        return f"the lecture pin names {pinned}, which is not in data/bundles/"
    l_pin = flatten(pb)[1]
    n = sum(l_pin.get(k) != v for k, v in l_new.items())
    return f"the lecture is pinned to {pinned}; {n} labels differ from it: check the slides (step 12)"


def announcement(cl):
    """Draft text for the instructor's Canvas announcement (C2: the instructor posts it)."""
    y = cl["years"]["new"] or {}
    return ("The \"Explore your major\" page now uses new Census data: "
            f"{y.get('rank', '[1-year]')} for the side-by-side and rank panels, and "
            f"{y.get('other', '[5-year]')} for the same-occupation and South Florida panels. "
            "Some numbers and labels changed. Open the page to see your major next to economics.")


def markdown(cl, top=20):
    if cl["first"]:
        return "First bundle: there is no live bundle to compare with.\n"
    w = cl["warnings"]
    names = {"W1": "economics pay moved > 8%", "W2": "a major's pay moved > 15% beyond its margins",
             "W3": "a rate moved > 2 points", "W4": "economics rank moved 5+ places",
             "W5": "an economics label moved two steps", "W6": "hidden cells changed by > 10% of a panel"}
    lines = [f"- Years: {cl['years'].get('old')} -> {cl['years']['new']}",
             f"- Dollars: {cl['dollars'].get('old')} -> {cl['dollars']['new']} (compared as published; no extra deflator)",
             f"- Numbers compared: {len(cl['numbers'])}; label changes: {len(cl['label_flips'])}; "
             f"rank moves of 5+: {len(cl['rank_moves'])}",
             f"- Cells added {len(cl['added'])}, dropped {len(cl['dropped'])}, newly hidden "
             f"{len(cl['newly_hidden'])}, newly shown {len(cl['newly_shown'])}",
             f"- New codes vs live (information): {cl['new_codes'] or 'none'}",
             f"- Lecture pin: {cl['pin']}", "", "Warnings (published anyway):"]
    for k, v in w.items():
        lines.append(f"- {k} {names[k]}: {len(v)}")
        for rec in v[:5]:
            lines.append(f"  - {rec}")
    lines += ["", f"Largest {top} relative changes:"]
    for r in cl["numbers"][:top]:
        lines.append(f"- {r['key']}: {r['old']} -> {r['new']} ({100 * r['rel']:+.1f}%)")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--live", default=None)
    a = ap.parse_args(argv)
    print(markdown(build(a.data, a.bundle, a.live)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
