"""After a runner build (spec/scheduler.yaml build_11_7): compare the new bundle with a saved copy of the live
bundle, and when the id differs, run the hard gates and the change list against it. Publishes nothing.

    python3 scripts/runner_report.py --live-copy DIR [--probe probe.json]
"""
import argparse
import filecmp
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import change_list  # noqa: E402
import gates  # noqa: E402
from vintage import V  # noqa: E402


def newest_bundle():
    b = sorted((ROOT / "data" / "bundles").iterdir(), key=lambda p: (p / "manifest.json").stat().st_mtime)
    return b[-1].name


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-copy", required=True)
    ap.add_argument("--probe")
    a = ap.parse_args(argv)
    live_dir = Path(a.live_copy)
    live = live_dir.name
    new = newest_bundle()
    lines = [f"Live bundle: `{live}`", f"Runner bundle: `{new}`", ""]
    files = sorted(json.loads((live_dir / "manifest.json").read_text())["files"])
    same = [f for f in files if filecmp.cmp(live_dir / f, ROOT / "data" / "bundles" / new / f, shallow=False)]
    lines.append(f"Data files byte-identical to live: {len(same)} of {len(files)}"
                 + ("" if len(same) == len(files) else f" (differ: {sorted(set(files) - set(same))})"))
    if new != live or len(same) != len(files):
        tmp = Path(tempfile.mkdtemp())                 # gates and change list on a scratch data dir
        (tmp / "bundles").mkdir()
        shutil.copytree(live_dir, tmp / "bundles" / f"live-{live}")
        shutil.copytree(ROOT / "data" / "bundles" / new, tmp / "bundles" / new)
        (tmp / "current.json").write_text(json.dumps({"bundle": f"live-{live}"}))
        rep = gates.run(tmp, new, f"live-{live}", str(V.dict1), str(V.dict5), a.probe)
        lines.append("Gates vs live: " + ", ".join(f"{g} {'PASS' if v['ok'] else 'FAIL'}" for g, v in rep["gates"].items()))
        cl = change_list.build(tmp, new, f"live-{live}")
        lines += ["", change_list.markdown(cl)]
    text = "\n".join(lines) + "\n"
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write("\n### Runner bundle vs live\n\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
