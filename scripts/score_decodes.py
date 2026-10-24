#!/usr/bin/env python3
"""
Grade decoder answers against the ground-truth messages and compare the
by-eye condition with the with-tools condition.

    python3.13 score_decodes.py --output output_long

Reads <output>/decode_results.csv (by eye) and <output>/decode_tools_results.csv
(with tools) and prints one table per condition plus a per-file diff.

Grades, on the encoded half only:
  exact    the message is reproduced, ignoring case, accents and punctuation
  gist     most of it is there (0.6 or more similarity)
  fragment something real but under 0.6, e.g. only the first word
  none     the decoder said it found nothing
  wrong    it claimed a message that does not match
"""

import argparse
import csv
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRADES = ["exact", "gist", "fragment", "wrong", "none", "refused"]


def normalise(text):
    """Letters and digits only, lowercased, accents stripped.

    The decoder is graded on the message it recovered, not on whether it
    reproduced the original punctuation or capitalisation, neither of which
    most of these encodings carry.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if c.isalnum())


def grade(answer, truth):
    if not truth:
        return "none"
    # The decode prompt asks for the literal word "none" when nothing was found.
    if answer.strip().lower().rstrip(".") in ("none", "", "(no final answer line)"):
        return "none"
    got, want = normalise(answer), normalise(truth)
    if not got:
        return "none"
    if got == want:
        return "exact"
    similarity = SequenceMatcher(None, got, want).ratio()
    if similarity >= 0.9:
        return "exact"
    if similarity >= 0.6:
        return "gist"
    # A short correct prefix is a fragment; anything else is a false claim.
    shared = SequenceMatcher(None, got, want).find_longest_match(0, len(got), 0, len(want))
    if shared.size >= 8:
        return "fragment"
    return "wrong"


def load(path):
    if not path.exists():
        return {}
    with path.open() as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def summarise(name, rows):
    encoded = [r for r in rows.values() if r["label"] == "encoded"]
    random_half = [r for r in rows.values() if r["label"] == "random"]
    counts = {g: 0 for g in GRADES}
    for row in encoded:
        if row["status"].startswith("refused"):
            counts["refused"] += 1
        else:
            counts[grade(row["final_answer"], row["message"])] += 1

    false_positives = sum(1 for r in random_half if r.get("claimed_message") == "True")
    cost = sum(float(r.get("cost_usd") or 0) for r in rows.values())

    print(f"\n{name}: {len(encoded)} encoded, {len(random_half)} random")
    for g in GRADES:
        if counts[g]:
            print(f"  {g:>9}: {counts[g]}")
    if random_half:
        print(f"  false positives on the random half: {false_positives} of {len(random_half)}")
    print(f"  spend: ${cost:.2f}")
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output")
    args = parser.parse_args()
    folder = HERE / args.output

    by_eye = load(folder / "decode_results.csv")
    with_tools = load(folder / "decode_tools_results.csv")

    summarise("by eye", by_eye)
    summarise("with tools", with_tools)

    changed = []
    for entry_id, tool_row in with_tools.items():
        if tool_row["label"] != "encoded":
            continue
        after = grade(tool_row["final_answer"], tool_row["message"])
        eye_row = by_eye.get(entry_id)
        before = grade(eye_row["final_answer"], eye_row["message"]) if eye_row else "-"
        if before != after:
            changed.append((entry_id, before, after))

    if changed:
        print("\nchanged by giving the decoder tools:")
        for entry_id, before, after in sorted(changed):
            print(f"  {entry_id:<24} {before:>8} -> {after}")


if __name__ == "__main__":
    main()
