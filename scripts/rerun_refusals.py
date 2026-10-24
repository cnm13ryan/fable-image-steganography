#!/usr/bin/env python3
"""
Rerun Fable decodes that came back as safeguard refusals until each one
yields a real answer, or the attempt cap is hit.

    python3.13 rerun_refusals.py output_astra            # both conditions
    python3.13 rerun_refusals.py output --max-attempts 3

The refusals are stochastic (pt_quote on Oct 8 passed on the third try),
so a fresh session is the fix. Each refused transcript is kept as
<id>.<suffix>.refused<n>.{md,json} before the rerun, and
decode_screenshots.py then sees the file as not done.
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

CONDITIONS = [
    # (results CSV, artifact suffix, extra flags for decode_screenshots.py)
    ("decode_results.csv", "decode", []),
    ("decode_tools_results.csv", "decode_tools", ["--tools"]),
]


def refused_ids(output_dir, csv_name):
    path = output_dir / csv_name
    if not path.exists():
        return []
    with path.open() as f:
        return [(row["label"], row["id"]) for row in csv.DictReader(f) if row["status"] == "refused"]


def attempts_so_far(output_dir, label, file_id, suffix):
    return len(list((output_dir / label).glob(f"{file_id}.{suffix}.refused*.md")))


def archive(output_dir, label, file_id, suffix, attempt):
    for ext in ("md", "json"):
        src = output_dir / label / f"{file_id}.{suffix}.{ext}"
        if src.exists():
            src.rename(output_dir / label / f"{file_id}.{suffix}.refused{attempt}.{ext}")


def rerun(output_dir, label, ids, flags, workers):
    cmd = [sys.executable, str(HERE / "decode_screenshots.py"), "--output", output_dir.name,
           "--only", label, "--workers", str(workers), *flags, "--ids", *ids]
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", help="output directory name, e.g. output_astra")
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    output_dir = HERE / args.output

    for round_number in range(1, args.max_attempts + 1):
        anything_rerun = False
        for csv_name, suffix, flags in CONDITIONS:
            for label in ("encoded", "random"):
                todo = []
                for row_label, file_id in refused_ids(output_dir, csv_name):
                    if row_label != label:
                        continue
                    done = attempts_so_far(output_dir, label, file_id, suffix)
                    if done + 1 >= args.max_attempts:
                        print(f"giving up on {label}/{file_id} ({suffix}) after {done + 1} attempts")
                        continue
                    archive(output_dir, label, file_id, suffix, done + 1)
                    todo.append(file_id)
                if todo:
                    anything_rerun = True
                    print(f"round {round_number}, {suffix}, {label}: rerunning {todo}", flush=True)
                    rerun(output_dir, label, todo, flags, args.workers)
        if not anything_rerun:
            break

    for csv_name, suffix, _ in CONDITIONS:
        left = refused_ids(output_dir, csv_name)
        print(f"{csv_name}: {len(left)} still refused {left}")


if __name__ == "__main__":
    main()
