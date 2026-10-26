"""Run one build step and log its cost (spec/scheduler.yaml build_11_7): elapsed time, peak memory of the step
(max RSS of its child processes), and free disk after it. Appends a row to $GITHUB_STEP_SUMMARY when set.

    python3 scripts/measure.py "<step name>" -- <command ...>
"""
import os
import resource
import shutil
import subprocess
import sys
import time


def main(argv):
    name, cmd = argv[0], argv[argv.index("--") + 1:]
    t0 = time.time()
    code = subprocess.call(cmd)
    secs = time.time() - t0
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss          # kilobytes on Linux, bytes on macOS
    gb = rss / (1024 ** 3 if sys.platform == "darwin" else 1024 ** 2)
    free = shutil.disk_usage(".").free / 1024 ** 3
    row = f"| {name} | {secs / 60:.1f} min | {gb:.1f} GB | {free:.1f} GB | {'ok' if code == 0 else f'exit {code}'} |"
    print(row)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(row + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
