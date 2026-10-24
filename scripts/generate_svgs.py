#!/usr/bin/env python3
"""
Generate the labelled set: 50 SVGs that hide a message and 50 plain drawings.

Encoded side, one entry per message in messages.json:
  1. Fable 5.1 (max effort) is asked to draw an ordinary picture that hides
     the message, using the strict wording from ../prompts/paint_blue.md.
  2. In the same conversation it is then asked for a short description of
     what carries the message (colours of the flowers, heights of the towers,
     ...). That is saved next to the SVG as <id>.notes.md.

Random side, one entry per seed in seeds.json:
  Fable 5.1 (max effort) draws whatever it likes within a loose topic.

A declined or SVG-less attempt is retried (--attempts, default 5): the
safety-classifier stops on instruction-style messages are nondeterministic,
and we need Fable itself to do every encoding. Files already on disk are
skipped, so re-running only fills in the gaps.

    python3.13 generate_svgs.py                 # everything
    python3.13 generate_svgs.py --only random   # one half
    python3.13 generate_svgs.py --limit 2       # smoke test
"""

import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from claude_cli import ModelFallbackError, ask

HERE = Path(__file__).resolve().parent

# Set in main() from --output and --encode-template, so a second batch with a
# different prompt wording can live in its own folder next to the first.
ENCODED_DIR = None
RANDOM_DIR = None
MANIFEST = None
ENCODE_PROMPT = None

NOTES_PROMPT = (HERE / "templates" / "encoding_notes.md").read_text()
RANDOM_PROMPT = (HERE / "templates" / "random.md").read_text()

# Greedy to the last closing tag: an SVG may nest another <svg> (a "voice memo"
# card did), and a non-greedy match would stop at the inner one and cut the
# outer element short.
SVG_PATTERN = re.compile(r"<svg[\s\S]*</svg>", re.IGNORECASE)


# ------------------------------------------------------------ asking for SVGs --

def extract_svg(text):
    match = SVG_PATTERN.search(text)
    return match.group(0) if match else None


def ask_for_svg(prompt, out_dir, entry_id, attempts):
    """Ask up to `attempts` times until a reply contains an SVG.

    Refusals are retried too: the same message is often accepted on another
    try. Every reply that came back without an SVG is kept as
    <id>.attempt<n>.md, so the declines stay visible on disk.
    Returns (svg_or_None, last_reply, total_cost).
    """
    cost = 0.0
    reply = None
    for attempt in range(1, attempts + 1):
        try:
            reply = ask(prompt)
        except ModelFallbackError as err:
            (out_dir / f"{entry_id}.attempt{attempt}.md").write_text(f"[{err}]")
            reply = None
            continue
        cost += reply.cost_usd
        svg = extract_svg(reply.text)
        if svg is not None:
            return svg, reply, cost
        (out_dir / f"{entry_id}.attempt{attempt}.md").write_text(reply.text)
    return None, reply, cost


def failure_status(reply):
    if reply is None:
        return "fallback_model"
    return "refused" if reply.stop_reason == "refusal" else "no_svg"


# ------------------------------------------------------------- the two sides --

def make_encoded(entry, attempts):
    out_dir = ENCODED_DIR
    svg, reply, cost = ask_for_svg(ENCODE_PROMPT.format(message=entry["message"]), out_dir, entry["id"], attempts)
    if svg is None:
        return {"status": failure_status(reply), "cost_usd": cost}

    (out_dir / f"{entry['id']}.svg").write_text(svg)

    notes = ask(NOTES_PROMPT, resume_session=reply.session_id)
    (out_dir / f"{entry['id']}.notes.md").write_text(notes.text)
    return {"status": "ok", "carrier": first_carrier_line(notes.text), "cost_usd": cost + notes.cost_usd}


def make_random(entry, attempts):
    out_dir = RANDOM_DIR
    svg, reply, cost = ask_for_svg(RANDOM_PROMPT.format(seed=entry["seed"]), out_dir, entry["id"], attempts)
    if svg is None:
        return {"status": failure_status(reply), "cost_usd": cost}

    (out_dir / f"{entry['id']}.svg").write_text(svg)
    return {"status": "ok", "cost_usd": cost}


def first_carrier_line(notes_text):
    """The notes start with a line "Carrier: ..."; that line goes into the manifest."""
    for line in notes_text.splitlines():
        if line.lower().startswith("carrier:"):
            return line.split(":", 1)[1].strip()
    return ""


# ------------------------------------------------------------------ driver --

def run_jobs(jobs, workers, attempts):
    """jobs: list of (entry, out_dir, worker_fn). Each result is saved as <id>.meta.json."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, entry, attempts): (entry, out_dir) for entry, out_dir, fn in jobs}
        for future in as_completed(futures):
            entry, out_dir = futures[future]
            try:
                result = future.result()
            except Exception as err:  # keep going; the manifest records it
                result = {"status": f"error: {str(err)[:200]}", "cost_usd": 0}
            (out_dir / f"{entry['id']}.meta.json").write_text(json.dumps({**entry, **result}, indent=2, ensure_ascii=False))
            print(f"[{result['status']:>8}] {entry['id']}  (${result['cost_usd']:.2f})", flush=True)


def write_manifest():
    """One row per generated file, assembled from all the <id>.meta.json files."""
    rows = []
    for label, out_dir in (("encoded", ENCODED_DIR), ("random", RANDOM_DIR)):
        for meta_path in sorted(out_dir.glob("*.meta.json")):
            meta = json.loads(meta_path.read_text())
            rows.append({**meta, "label": label, "file": f"{label}/{meta['id']}.svg"})

    columns = ["id", "label", "status", "language", "category", "message", "seed", "carrier", "file", "cost_usd"]
    with MANIFEST.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"manifest: {MANIFEST}  ({len(rows)} rows, ${sum(r['cost_usd'] for r in rows):.2f} total)")


def not_done_yet(entries, out_dir):
    return [e for e in entries if not (out_dir / f"{e['id']}.svg").exists()]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["encoded", "random"])
    parser.add_argument("--limit", type=int, help="only the first N entries of each side")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--attempts", type=int, default=5, help="tries per entry before giving up")
    parser.add_argument("--output", default="output", help="folder for the generated files (relative to this script)")
    parser.add_argument("--encode-template", default="encode.md", help="file in templates/ with the encoding prompt")
    parser.add_argument("--messages", default="messages.json", help="file with the messages to encode")
    args = parser.parse_args()

    global ENCODED_DIR, RANDOM_DIR, MANIFEST, ENCODE_PROMPT
    ENCODED_DIR = HERE / args.output / "encoded"
    RANDOM_DIR = HERE / args.output / "random"
    MANIFEST = HERE / args.output / "manifest.csv"
    ENCODE_PROMPT = (HERE / "templates" / args.encode_template).read_text()

    ENCODED_DIR.mkdir(parents=True, exist_ok=True)
    RANDOM_DIR.mkdir(parents=True, exist_ok=True)

    jobs = []
    if args.only != "random":
        messages = json.loads((HERE / args.messages).read_text())[: args.limit]
        jobs += [(e, ENCODED_DIR, make_encoded) for e in not_done_yet(messages, ENCODED_DIR)]
    if args.only != "encoded":
        seeds = json.loads((HERE / "seeds.json").read_text())[: args.limit]
        jobs += [(e, RANDOM_DIR, make_random) for e in not_done_yet(seeds, RANDOM_DIR)]

    print(f"{len(jobs)} jobs to run with {args.workers} workers", flush=True)
    run_jobs(jobs, args.workers, args.attempts)
    write_manifest()


if __name__ == "__main__":
    main()
