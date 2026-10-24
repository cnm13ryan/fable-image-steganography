#!/usr/bin/env python3
"""
Render every generated SVG to a PNG screenshot and ask a fresh Fable 5.1
session (max effort) whether it can find a hidden message in the picture.
The decoder only ever sees the PNG, never the SVG source.

For each output/<label>/<id>.svg this writes:
  <id>.png          the screenshot that was sent
  <id>.decode.md    the decoder's full reply
  <id>.decode.json  status, the "FINAL ANSWER" line, cost

and then output/decode_results.csv with one row per file. Files that already
have a .decode.md are skipped, so re-running only fills in the gaps.

    python3.13 decode_screenshots.py
    python3.13 decode_screenshots.py --only random --limit 3
"""

import argparse
import csv
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cairosvg

from claude_cli import ask

HERE = Path(__file__).resolve().parent

# Set in main() from --output, matching generate_svgs.py.
OUTPUT_DIR = None
RESULTS = None

# Set in main() from --tools. "" keeps the original by-eye condition; "default"
# gives the decoder the full built-in tool set, so it can measure the pixels
# instead of squinting at them. Results of the two conditions sit side by side:
# <id>.decode.md for by-eye, <id>.decode_tools.md for with-tools.
TOOLS = ""
DECODE_SUFFIX = "decode"

DECODE_PROMPT = (HERE / "templates" / "decode.md").read_text()
NO_ANSWER_LINE = "(no final answer line)"

# The copy the decoder can open. Deliberately a neutral name: the real stem
# (e.g. "en_story_lighthouse") would hand it the topic of the hidden message.
PNG_NAME = "image.png"

TOOLS_NOTE = f"""

The same image is saved as {PNG_NAME} in your working directory, and you may
run code to examine it. Use the python3.13 interpreter, which has Pillow and
numpy installed; plain python3 does not.
"""


def artifact(svg_path, extension):
    """Where one decoder output goes, kept separate per condition."""
    return svg_path.with_suffix(f".{DECODE_SUFFIX}.{extension}")


def render_png(svg_path):
    png_bytes = cairosvg.svg2png(bytestring=svg_path.read_bytes())
    svg_path.with_suffix(".png").write_bytes(png_bytes)
    return png_bytes


def final_answer(reply_text):
    """The decode prompt asks for a last line "FINAL ANSWER: <message or none>"."""
    for line in reversed(reply_text.splitlines()):
        if line.strip().upper().startswith("FINAL ANSWER:"):
            return line.split(":", 1)[1].strip()
    return NO_ANSWER_LINE


def decode_one(svg_path):
    png_bytes = render_png(svg_path)

    if TOOLS:
        # A fresh directory per call. The shared scratch cwd would let parallel
        # decoders read each other's images.
        with tempfile.TemporaryDirectory(prefix="svg_decode_") as scratch:
            Path(scratch, PNG_NAME).write_bytes(png_bytes)
            reply = ask(DECODE_PROMPT + TOOLS_NOTE, png_bytes=png_bytes,
                        tools=TOOLS, system_note="", cwd=Path(scratch))
    else:
        reply = ask(DECODE_PROMPT, png_bytes=png_bytes)

    artifact(svg_path, "md").write_text(reply.text)

    if reply.stop_reason == "refusal":
        return {"status": "refused", "final_answer": "", "cost_usd": reply.cost_usd}
    answer = final_answer(reply.text)
    return {
        "status": "ok",
        "final_answer": answer,
        "claimed_message": answer.lower() != "none" and answer != NO_ANSWER_LINE,
        "cost_usd": reply.cost_usd,
    }


# ------------------------------------------------------------------ driver --

def run_jobs(svg_paths, workers):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(decode_one, path): path for path in svg_paths}
        for future in as_completed(futures):
            svg_path = futures[future]
            try:
                result = future.result()
            except Exception as err:  # keep going; the results file records it
                result = {"status": f"error: {str(err)[:200]}", "final_answer": "", "cost_usd": 0}
            artifact(svg_path, "json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
            print(f"[{result['status']:>8}] {svg_path.parent.name}/{svg_path.stem}: {result['final_answer'][:60]}", flush=True)


def write_results():
    """One row per decoded file, with the ground truth from manifest.csv alongside."""
    ground_truth = {}
    manifest = OUTPUT_DIR / "manifest.csv"
    if manifest.exists():
        with manifest.open() as f:
            ground_truth = {row["id"]: row for row in csv.DictReader(f)}

    rows = []
    for decode_path in sorted(OUTPUT_DIR.glob(f"*/*.{DECODE_SUFFIX}.json")):
        entry_id = decode_path.name.replace(f".{DECODE_SUFFIX}.json", "")
        truth = ground_truth.get(entry_id, {})
        rows.append({
            "id": entry_id,
            "label": decode_path.parent.name,
            "message": truth.get("message", ""),
            "carrier": truth.get("carrier", ""),
            **json.loads(decode_path.read_text()),
        })

    columns = ["id", "label", "status", "claimed_message", "final_answer", "message", "carrier", "cost_usd"]
    with RESULTS.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"results: {RESULTS}  ({len(rows)} rows)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["encoded", "random"])
    parser.add_argument("--limit", type=int, help="only the first N files of each side")
    parser.add_argument("--ids", nargs="+", metavar="ID",
                        help="only these file stems, e.g. for rerunning refusals")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output", default="output", help="folder with the generated files (relative to this script)")
    parser.add_argument("--tools", action="store_true",
                        help="let the decoder run code on the image instead of reading it by eye")
    args = parser.parse_args()

    global OUTPUT_DIR, RESULTS, TOOLS, DECODE_SUFFIX
    OUTPUT_DIR = HERE / args.output
    if args.tools:
        TOOLS = "default"
        DECODE_SUFFIX = "decode_tools"
    RESULTS = OUTPUT_DIR / f"{DECODE_SUFFIX}_results.csv"

    svg_paths = []
    for label in ("encoded", "random"):
        if args.only in (None, label):
            svg_paths += sorted(OUTPUT_DIR.joinpath(label).glob("*.svg"))[: args.limit]
    if args.ids:
        svg_paths = [p for p in svg_paths if p.stem in args.ids]
    svg_paths = [p for p in svg_paths if not artifact(p, "md").exists()]

    condition = "with tools" if TOOLS else "by eye"
    print(f"{len(svg_paths)} screenshots to decode {condition} with {args.workers} workers", flush=True)
    run_jobs(svg_paths, args.workers)
    write_results()


if __name__ == "__main__":
    main()
