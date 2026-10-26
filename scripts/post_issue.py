"""Post a rendered issue body once per key, and optionally close it (spec/scheduler.yaml dry_run_11_8).

    python3 scripts/post_issue.py --body-file F --kind KIND [--dry-run] [--close "comment"]

The key comes from the body's '<!-- dashboard-key: ... -->' line; a dry run prefixes it with 'dryrun:'. Needs GH_TOKEN.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import issues  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--kind", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--close")
    a = ap.parse_args(argv)
    body, key = issues.split_key(Path(a.body_file).read_text())
    if key is None:
        sys.exit("the body has no dashboard-key line")
    key = ("dryrun:" + key) if a.dry_run else key
    for lab in ["data-bot", a.kind] + (["dry-run"] if a.dry_run else []):
        issues.run_gh(["label", "create", lab, "--force", "--color", "BFD4F2" if lab != "dry-run" else "EDEDED"])
    res = issues.post(issues.title_of(body), body, key, [a.kind], dry_run=a.dry_run)
    print(f"{key}: {res}")
    if res != "duplicate" and a.close:
        issues.run_gh(["issue", "close", res, "--comment", a.close])
        print(f"closed {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
