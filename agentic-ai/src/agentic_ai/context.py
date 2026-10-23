from __future__ import annotations

import json
from typing import Any

from .errors import ProtocolError


def estimate_tokens(text: str) -> int:
    """Conservative transport-independent estimate, not a tokenizer claim."""
    return max(1, (len(text.encode("utf-8")) + 2) // 3)


def _render_entry(entry: dict[str, Any], *, compact: bool = False) -> str:
    label = f"turn {entry.get('turn', '?')} {entry.get('kind', 'history')}"
    content = entry.get("compact", "") if compact else ""
    if not content:
        content = entry.get("content", "")
    return f"[{label}]\n{content}"


def build_messages(
    *,
    system_prompt: str,
    task_prompt: str,
    history: list[dict[str, Any]],
    context_length: int,
    num_predict: int,
    safety_reserve: int,
) -> list[dict[str, str]]:
    input_tokens = context_length - num_predict - safety_reserve
    if input_tokens <= 0:
        raise ProtocolError("No input token budget remains")
    fixed_tokens = estimate_tokens(system_prompt) + estimate_tokens(task_prompt) + 20
    remaining_tokens = input_tokens - fixed_tokens
    if remaining_tokens < 0:
        raise ProtocolError("System and task prompts exceed the context budget; split the task")

    selected: list[str] = []
    omitted = 0
    for entry in reversed(history):
        rendered = _render_entry(entry)
        cost = estimate_tokens(rendered) + 2
        if cost <= remaining_tokens:
            selected.append(rendered)
            remaining_tokens -= cost
            continue
        compact = _render_entry(entry, compact=True)
        compact = compact[:2000]
        compact_cost = estimate_tokens(compact) + 2
        if compact_cost <= remaining_tokens:
            selected.append(compact)
            remaining_tokens -= compact_cost
        else:
            omitted += 1

    if len(selected) < len(history):
        omitted = max(omitted, len(history) - len(selected))
    selected.reverse()
    history_text = ""
    if selected or omitted:
        sections = []
        if omitted:
            sections.append(
                f"[{omitted} older steps omitted from this prompt; their full records remain on disk]"
            )
        sections.extend(selected)
        history_text = "\n\nDurable previous steps (newest relevant steps retained):\n" + "\n\n".join(
            sections
        )
    user = task_prompt + history_text + "\n\nReturn the next exactly-one JSON object now."
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]
    actual = sum(estimate_tokens(message["content"]) for message in messages)
    if actual > input_tokens + 25:
        raise ProtocolError("Context compaction failed to fit the input budget")
    return messages


def compact_json(value: Any, limit: int = 800) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"
