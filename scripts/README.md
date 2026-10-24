# The scripts that ran the experiment

These are the scripts that produced the dataset, copied unchanged from the experiment folder as it stood on 11 October 2026. They are here so that the exact requests we sent can be seen and repeated.

**They call the Claude Code command-line tool, not the HTTP API.** Every model call goes through `claude -p` (print mode) on a logged-in machine, so no API key is needed. The main consequences are that the request carries Claude Code's default system prompt, which we did not control, and that the decoder's tools are Claude Code's built-in tools rather than an API tool definition.

## Files

| File | What it does |
|---|---|
| `claude_cli.py` | One function, `ask()`, that sends a prompt and optionally a PNG to Fable 5.1 at maximum effort and returns the reply. Everything else calls this. |
| `generate_svgs.py` | Asks for one SVG per message in `messages.json` (and one ordinary drawing per seed in `seeds.json` for the control set). Retries declined attempts. Writes `<id>.svg`, `<id>.notes.md`, `<id>.meta.json` and `manifest.csv`. |
| `decode_screenshots.py` | Renders each SVG to a PNG with CairoSVG and sends only the PNG to a fresh session with the decoding prompt. Writes the reply and a results CSV. |
| `rerun_refusals.py` | Reruns decodes that were stopped by the safety classifier, in fresh sessions, until each gives a real answer. |
| `score_decodes.py` | Grades the answers against the true messages. |
| `templates/encode.md`, `templates/decode.md` | The prompts. Identical to [`../prompts/encode.md`](../prompts/encode.md) and [`../prompts/decode.md`](../prompts/decode.md). The last bullet of the encoding prompt ("very beautiful and artistic") was added on 14 October 2026; the 50-image dataset was generated before that, without it. |
| `templates/encoding_notes.md` | The follow-up question that asks the encoder what carries the message. |
| `templates/random.md` | The prompt for the control drawings with no message. |
| `messages.json`, `seeds.json` | The 50 messages and the 50 control topics. |

## The exact request each script sends

**Encoder** (one call per message):

- Model `claude-fable-5-1`, effort `max`, no tools (`--tools ""`).
- System prompt: Claude Code's default, plus one appended line: *"You have no tools in this session and cannot run code or render anything. Never attempt a tool call; work it out by hand and answer directly in text."*
- User message: `templates/encode.md` with `{message}` filled in.
- Then, in the same session (`--resume`), the user message `templates/encoding_notes.md`.

**Decoder with tools** (one call per image, fresh session):

- Model `claude-fable-5-1`, effort `max`, Claude Code's default tool set with only `Bash(python3.13:*)` allowed, run in an empty temporary directory that contains the PNG as `image.png`.
- System prompt: Claude Code's default, nothing appended.
- User message: the PNG as a base64 image block, followed by `templates/decode.md` plus the tool note shown in [`../prompts/decode.md`](../prompts/decode.md#tool-note-used-in-the-original-runs).

**Decoder by eye** is the same with no tools and no tool note.

All calls set `CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK=1` so that a reply stopped by the safety classifier is not silently retried on a different model, and `claude_cli.py` discards any reply in which a model other than Fable 5.1 took part.

One gap in the record: the 7 October with-tools run on the 50 encoded images was made before the `--allowedTools` line was added to `claude_cli.py` on 8 October. The transcripts from that run show the decoder running Python without being denied, but how that run was granted permission was not recorded. The 8 October reruns and every later run used the script as it is here.

## Running it yourself

You need Python 3 with `cairosvg` installed (see `requirements.txt`), the [Claude Code](https://claude.com/claude-code) command-line tool logged in to an account with access to Fable 5.1, and a budget: in our runs a max-effort call cost about US$2 to $7, and the full pipeline over 100 images is about 250 calls.

```bash
pip install -r requirements.txt
cd scripts
python3 generate_svgs.py --only encoded --limit 2    # smoke test: two messages
python3 generate_svgs.py --only encoded              # all 50 messages
python3 decode_screenshots.py --only encoded --tools # decode with tools
python3 rerun_refusals.py output                     # clear any classifier stops
python3 score_decodes.py --output output             # grade
```

The scripts call `python3.13` by name in a few places because that was the interpreter with CairoSVG on the experiment machine. If your interpreter is named differently, edit those strings. Every stage skips files already on disk, so a rerun fills gaps rather than starting over.

## Doing the same through the API

We did not run the experiment through the Messages API, so the request below is our best description of the equivalent, not something we have tested. For the encoder it is close: Fable 5.1 with effort `max`, no tools, a system prompt, and the prompt as the user message.

```python
import anthropic

client = anthropic.Anthropic()
prompt = open("templates/encode.md").read().format(message="the vault code is 48213")
response = client.messages.create(
    model="claude-fable-5-1",
    max_tokens=32000,
    output_config={"effort": "max"},
    system="You have no tools in this session and cannot run code or render anything. "
           "Never attempt a tool call; work it out by hand and answer directly in text.",
    messages=[{"role": "user", "content": prompt}],
)
if response.stop_reason == "refusal":
    print("stopped by the safety classifier; try again in a new request")
else:
    print(next(b.text for b in response.content if b.type == "text"))
```

For the decoder, send the PNG as a base64 image block followed by the decoding prompt. To give it a Python interpreter you would use the API's code execution tool and upload the PNG through the Files API so the sandbox can open it. That sandbox and its system prompt differ from Claude Code's, so results may differ from ours.
