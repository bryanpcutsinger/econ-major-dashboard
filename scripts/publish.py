"""Step 9: publish a bundle after the gates, roll back, and the stale check (spec/gates.yaml).

  publish   run every hard gate vs the live bundle. All pass -> data/current.json names the candidate
            (with the old one as 'previous'), data/history.json gets a line, and the new-data issue is
            rendered with the change list. Any fail -> current.json untouched, the gate-hold issue
            (revision if only H9 failed) is rendered, exit 1.
  rollback  current.json -> its 'previous' bundle (no gates: that bundle passed them). No previous ->
            exit 1, nothing changed.
  stale     more than 15 months since the newest published source -> render the stale issue.

Rendering an issue writes its body (to --issue-out, else prints it). Posting it to GitHub is step 11,
on the instructor's say-so: this script has no code that posts.

Run from the repo root:
  python3 scripts/publish.py <bundle id> --dictionary-1y <csv> --dictionary-5y <csv> [--probe <json>]
  python3 scripts/publish.py --rollback
  python3 scripts/publish.py --stale-check --published 2025-12-04 [--today 2027-04-01]
All take --data <dir> (default data/) and --issue-out <file>.
"""
import argparse
import datetime as dt
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import change_list  # noqa: E402
import gates  # noqa: E402

TEMPLATES = ROOT / "templates" / "issues"
STALE_MONTHS = 15


def render(name, **fields):
    return string.Template((TEMPLATES / f"{name}.md").read_text()).substitute(fields)


def current(data):
    p = Path(data) / "current.json"
    return json.loads(p.read_text()) if p.exists() else None


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")


def log(data, entry):
    p = Path(data) / "history.json"
    hist = json.loads(p.read_text()) if p.exists() else []
    hist.append(dict(entry, time=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    write_json(p, hist)


def publish(data, bid, dictionary_1y=None, dictionary_5y=None, probe=None):
    """Returns (exit code, template name or None, issue body or message)."""
    cur = current(data)
    live = cur["bundle"] if cur else None
    if live == bid:
        return 0, None, f"{bid} is already live; nothing to do"
    rep = gates.run(data, bid, live, dictionary_1y, dictionary_5y, probe)
    failed = [g for g, v in rep["gates"].items() if not v["ok"]]
    if failed:
        name = "revision" if failed == ["H9_source_revision"] else "gate-hold"
        lines = [f"- **{g}**: " + "; ".join(rep["gates"][g]["problems"][:10]) for g in failed]
        body = render(name, n_failed=len(failed), candidate=bid, live=live or "(none)",
                      failed="\n".join(lines), report=gates.summary(rep))
        return 1, name, body
    cl = change_list.build(data, bid, live)
    write_json(Path(data) / "current.json", {"bundle": bid, "previous": live})
    log(data, {"action": "publish", "bundle": bid, "previous": live})
    body = render("new-data", candidate=bid, live=live or "(none: first bundle)",
                  change_list=change_list.markdown(cl), announcement=cl["announcement"])
    return 0, "new-data", body


def rollback(data):
    cur = current(data)
    prev = (cur or {}).get("previous")
    if not prev:
        return 1, None, "no previous bundle: nothing changed"
    if not (Path(data) / "bundles" / prev / "manifest.json").exists():
        return 1, None, f"previous bundle {prev} is not in bundles/: nothing changed"
    hist = json.loads((Path(data) / "history.json").read_text()) if (Path(data) / "history.json").exists() else []
    # the restored bundle's own 'previous' = what it replaced when it was published, if logged
    before = next((h.get("previous") for h in reversed(hist) if h["action"] == "publish" and h["bundle"] == prev), None)
    write_json(Path(data) / "current.json", {"bundle": prev, "previous": before})
    log(data, {"action": "rollback", "bundle": prev, "from": cur["bundle"]})
    return 0, None, f"rolled back {cur['bundle']} -> {prev}"


def months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month) - (b.day < a.day)


def stale(data, published, today):
    """(is stale, issue body or None). published / today are dates."""
    m = months_between(published, today)
    if m <= STALE_MONTHS:
        return False, None
    cur = current(data)
    return True, render("stale", months=m, live=(cur or {}).get("bundle", "(none)"), published=published.isoformat())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", nargs="?")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--dictionary-1y")
    ap.add_argument("--dictionary-5y")
    ap.add_argument("--probe")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--stale-check", action="store_true")
    ap.add_argument("--published", type=dt.date.fromisoformat)
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--issue-out")
    a = ap.parse_args(argv)
    if a.rollback:
        code, name, body = rollback(a.data)
    elif a.stale_check:
        is_stale, body = stale(a.data, a.published, a.today)
        code, name, body = 0, ("stale" if is_stale else None), (body or "not stale")
    elif a.bundle:
        code, name, body = publish(a.data, a.bundle, a.dictionary_1y, a.dictionary_5y, a.probe)
    else:
        ap.error("give a bundle id, --rollback, or --stale-check")
    if name and a.issue_out:
        Path(a.issue_out).write_text(body)
        print(f"issue ({name}) written to {a.issue_out}")
    else:
        print(body)
    return code


if __name__ == "__main__":
    sys.exit(main())
