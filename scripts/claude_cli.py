"""
One function, ask(), that sends a prompt (and optionally a PNG image) to
Claude Fable 5.1 at max effort and returns the reply.

Every call goes through the logged-in `claude` CLI in print mode, so no API
key is needed. The input is sent as a stream-json user message because that
is the only way the CLI accepts an image.
"""

import base64
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MODEL = "claude-fable-5-1"
EFFORT = "max"
CALL_TIMEOUT_SECONDS = 30 * 60

# A scratch cwd so the model sessions do not pick up this repo's CLAUDE.md
# or see the other SVGs.
SCRATCH_CWD = Path("/tmp/svg_screenshot_experiment_scratch")

# Even with every tool removed, Fable at max effort sometimes writes out a Bash
# call to "verify the encoding" and ends its turn without an SVG. Say so up front.
NO_TOOLS_NOTE = ("You have no tools in this session and cannot run code or render "
                 "anything. Never attempt a tool call; work it out by hand and answer "
                 "directly in text.")


@dataclass
class Reply:
    text: str
    session_id: str
    stop_reason: str
    cost_usd: float


class ModelFallbackError(RuntimeError):
    """Raised when a model other than MODEL produced part of the reply.

    After a safety-classifier stop, Claude Code can silently retry the turn on
    another model (seen: Fable 5.1 -> Opus 4.8). Those replies must not end up
    in the experiment, which is Fable-only.
    """


def ask(prompt: str, png_bytes: Optional[bytes] = None, resume_session: Optional[str] = None,
        tools: str = "", system_note: str = NO_TOOLS_NOTE, cwd: Optional[Path] = None) -> Reply:
    """Run one model turn. Pass resume_session to continue an earlier conversation.

    tools goes straight to --tools: "" disables everything, "default" allows the
    whole built-in set. When tools are on, pass a per-call cwd so that concurrent
    sessions cannot read each other's files.
    """
    command = [
        "claude", "-p",
        "--model", MODEL,
        "--effort", EFFORT,
        "--tools", tools,
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
    ]
    if tools:
        # Print mode auto-denies anything that would normally prompt, so without
        # this the "with tools" decoder cannot run a single line of code and
        # silently degrades to a by-eye read. Only the interpreter is allowed.
        command += ["--allowedTools", "Bash(python3.13:*)"]
    if system_note:
        command += ["--append-system-prompt", system_note]
    if resume_session:
        command += ["--resume", resume_session]

    work_dir = Path(cwd) if cwd else SCRATCH_CWD
    work_dir.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        command,
        input=user_message_json(prompt, png_bytes),
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=CALL_TIMEOUT_SECONDS,
        env={**os.environ, "CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK": "1"},
    )

    events = parse_events(process.stdout)
    result = last_result_event(events)
    if result is None:
        raise RuntimeError(f"claude exited {process.returncode} without a result: {process.stderr[-500:]}")

    models = models_that_answered(events)
    if models - {MODEL}:
        raise ModelFallbackError(f"reply was produced by {sorted(models)}, not only {MODEL}")

    return Reply(
        text=result.get("result", ""),
        session_id=result.get("session_id", ""),
        stop_reason=result.get("stop_reason", ""),
        cost_usd=result.get("total_cost_usd", 0.0),
    )


def user_message_json(prompt: str, png_bytes: Optional[bytes]) -> str:
    """Build the single stream-json line that the CLI reads from stdin."""
    content = []
    if png_bytes is not None:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(png_bytes).decode("ascii"),
            },
        })
    content.append({"type": "text", "text": prompt})
    message = {"type": "user", "message": {"role": "user", "content": content}}
    return json.dumps(message) + "\n"


def parse_events(stdout: str) -> list:
    """The CLI streams one json event per line."""
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def last_result_event(events: list) -> Optional[dict]:
    """The last event of type "result" carries the final answer, cost and session id."""
    results = [e for e in events if e.get("type") == "result"]
    return results[-1] if results else None


def models_that_answered(events: list) -> set:
    """Every assistant event names the model that produced it.

    The CLI inserts its own notices (e.g. "safeguards stopped the response")
    as assistant events with model "<synthetic>"; those are not a model reply.
    """
    models = {e["message"].get("model") for e in events if e.get("type") == "assistant"}
    return models - {"<synthetic>"}
