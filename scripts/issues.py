"""Step 11.3 issues (spec/scheduler.yaml issues_11_3): the kind, the announcement wording, the de-dup key, and posting.

    kind_of(candidate_manifest, live_manifest)  -> new-data | revision-published | rebuild
    announcement(kind, change_list)              -> the draft Canvas text, or None (rebuild)
    with_key(body, key)                          -> body + a hidden '<!-- dashboard-key: KEY -->' line
    post(title, body, key, labels, gh=..., dry_run=False) -> 'posted' | 'duplicate'

Posting runs `gh` (GH_TOKEN in the workflow). Tests pass a stub for `gh`; real posting starts at 11.8.
"""
import json
import re
import subprocess
import tempfile

KEY_RE = re.compile(r"<!-- dashboard-key: (.+?) -->")
LABEL = "data-bot"


def kind_of(cand, live):
    if live is None or cand.get("years") != live.get("years"):
        return "new-data"
    if cand.get("sources", {}) != live.get("sources", {}):
        return "revision-published"
    return "rebuild"


def announcement(kind, cl):
    y = (cl.get("years") or {}).get("new") or {}
    years = (f"{y.get('rank', '[1-year]')} for the side-by-side and rank panels, and {y.get('other', '[5-year]')} for "
             "the other panels")
    if kind == "new-data":
        return ("The \"Explore your major\" page now uses new Census data: " + years + ". Some numbers and labels "
                "changed. Open the page to see your major next to economics.")
    if kind == "revision-published":
        return ("The Census Bureau revised data the \"Explore your major\" page uses (" + years + "), and the page now "
                "shows the revised numbers. Some numbers may have changed a little.")
    return None                                        # rebuild: same data, no announcement (ruling 2026-10-26)


def with_key(body, key):
    return body.rstrip("\n") + f"\n\n<!-- dashboard-key: {key} -->\n"


def run_gh(args, input_text=None):
    """The real gh call: returns stdout. Raises on a non-zero exit."""
    r = subprocess.run(["gh"] + args, capture_output=True, text=True, input=input_text)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {r.stderr.strip()}")
    return r.stdout


def existing_keys(gh=run_gh):
    out = gh(["issue", "list", "--label", LABEL, "--state", "all", "--json", "number,title,body", "--limit", "200"])
    keys = set()
    for issue in json.loads(out or "[]"):
        m = KEY_RE.search(issue.get("body") or "")
        if m:
            keys.add(m.group(1))
    return keys


def post(title, body, key, labels, gh=run_gh, dry_run=False):
    """Post once per key. A dry run adds a [DRY RUN] title prefix and the dry-run label (11.8 closes it)."""
    if key in existing_keys(gh):
        return "duplicate"
    labels = [LABEL] + list(labels) + (["dry-run"] if dry_run else [])
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(with_key(body, key))
        path = fh.name
    args = ["issue", "create", "--title", ("[DRY RUN] " if dry_run else "") + title, "--body-file", path]
    for lab in labels:
        args += ["--label", lab]
    gh(args)
    return "posted"


def title_of(body):
    """The first '# ' line of a rendered template is the issue title."""
    first = body.lstrip().splitlines()[0]
    return first[2:].strip() if first.startswith("# ") else first.strip()
