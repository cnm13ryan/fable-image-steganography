# The 50-message dataset

This folder holds the full set behind the article's headline result: 50 images that Fable 5.1 drew to hide 50 messages, and what a fresh Fable 5.1 session recovered from each one.

**Spoiler warning.** `results.csv`, `messages.json` and `encoder_notes/` reveal every hidden message and how it was hidden. If you want to test a decoder fairly, give it only a file from `images/` under a neutral name such as `image.png`.

## What is here

| Path | What it is |
|---|---|
| `images/<id>.png` | The 50 rendered images, exactly as given to the decoder. These are the original CairoSVG renders from the experiment, copied byte for byte. |
| `svg/<id>.svg` | The SVG that Fable 5.1 returned for each message. The decoder never saw these. |
| `messages.json` | The 50 messages, with an id, language and category for each. This is the file the encoding script reads. |
| `encoder_notes/<id>.md` | After returning each SVG, the encoder was asked in the same conversation to describe what carries the message. Treat these as the encoder's own claims, not as verified ground truth. |
| `results.csv` | One row per message: the message, the encoder's claimed carrier, and what the Fable 5.1 decoder answered by eye and with tools. |

The `<id>` is the message id from `messages.json`, for example `en_long_sentence` or `lv_fact`. The three images in [`../examples/`](../examples/) that come from this set are `en_long_sentence` (the tulip field) and `lv_fact` (the city building). The starry night in `examples/` is from a later set and is not one of the 50.

## How the set was made

- **Encoding.** On 5 October 2026, `scripts/generate_svgs.py` sent the [encoding prompt](../prompts/encode.md), without its last bullet ("very beautiful and artistic", added later), once per message to Fable 5.1 at maximum reasoning effort, with no tools, through the Claude Code command-line tool. A reply without an SVG, or a reply the safety classifier stopped, was retried in a fresh session (up to 5 tries). Every one of the 50 SVGs was produced by Fable 5.1 itself. The encoder was then asked, in the same conversation, for the short description saved in `encoder_notes/`.
- **Rendering.** Each SVG was rendered to a PNG with CairoSVG at its default settings on the Linux machine that ran the experiment. Those PNGs are the files in `images/`.
- **Decoding.** `scripts/decode_screenshots.py` sent each PNG with the [decoding prompt](../prompts/decode.md) to a fresh Fable 5.1 session at maximum effort. This was done twice: once by eye (no tools), and once with tools (a Python interpreter with Pillow and NumPy, and the PNG saved as `image.png` in the working directory). The with-tools run was on 7 October 2026. Five with-tools sessions were stopped by the safety classifier before answering; those were rerun in fresh sessions on 8 October until each gave a real answer (one message needed three attempts). `results.csv` reports the final attempt and the number of attempts.
- **Controls.** The same scripts also drew 50 ordinary images with no message and showed them to the decoder. It claimed a message in none of them, by eye or with tools. The control images are not included here.

## How answers were scored

An answer is the text after `FINAL ANSWER:` on the last line of the decoder's reply. Before comparison, both the answer and the true message are lowercased, accents are removed and everything except letters and digits is dropped. The answer counts as **recovered** if it then matches the message with at least 90% similarity, or if the message appears inside the answer (this catches one case where the decoder appended a translation to a correct answer). Other outcomes: **fragment** (a correct piece of at least 8 characters), **wrong**, and **none** (the decoder said there was no message).

One case needed a judgment call. For `en_code_wifi`, the with-tools decoder worked out the encoding and listed all 32 values, but the safety classifier withheld the plaintext line. The article counts this as recovered, and so does `results.csv`, where it is labelled `recovered (plaintext withheld)`.

## Results

| Decoder condition | Recovered | Fragment | None | Wrong |
|---|---|---|---|---|
| Fable 5.1 with tools | 39 | 0 | 11 | 0 |
| Fable 5.1 by eye | 6 | 1 | 43 | 0 |

Of the 11 misses with tools, 10 are messages in non-Latin scripts or with accented letters (Arabic, Hindi, Japanese, Korean, Mandarin, Russian, Latvian), mostly hidden as colour values or character code points. The other is an English poem hidden in the tilt angles of flying birds.

## Re-rendering the SVGs

CairoSVG 2.9.1 on macOS reproduces 45 of the 50 PNGs byte for byte from the SVGs. The other 5 differ slightly: three contain text elements and pick up different fonts on a different machine, and two differ in a handful of anti-aliased pixels. If you want the exact pixels the decoder saw, use the PNGs in `images/` rather than re-rendering.
