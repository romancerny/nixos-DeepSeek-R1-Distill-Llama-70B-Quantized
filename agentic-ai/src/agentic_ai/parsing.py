from __future__ import annotations

import json
import re
from typing import Any

from .errors import PlanValidationError, ProtocolError
from .plan import safe_run_path


_LEADING_REASONING = re.compile(
    r"\A\s*<(think|thought)>(.*?)</\1>\s*", re.DOTALL
)
_LEADING_OPEN = re.compile(r"\A\s*<(think|thought)>")
_CALL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def strip_reasoning(text: str) -> str:
    remaining = text
    while True:
        match = _LEADING_REASONING.match(remaining)
        if match is None:
            break
        remaining = remaining[match.end() :]
    if _LEADING_OPEN.match(remaining):
        raise ProtocolError("Unterminated leading reasoning block; response is truncated")
    return remaining.strip()


def parse_json_object(text: str, *, done_reason: str | None = None) -> dict[str, Any]:
    if done_reason == "length":
        raise ProtocolError("Model response was truncated at the output token limit")
    cleaned = strip_reasoning(text)
    if not cleaned:
        raise ProtocolError("Model returned an empty response")
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProtocolError(
            f"Expected exactly one JSON object without Markdown or prose: {exc.msg} "
            f"at line {exc.lineno} column {exc.colno}"
        ) from exc
    if not isinstance(value, dict):
        raise ProtocolError("The response must be one JSON object")
    return value


def validate_agent_response(value: dict[str, Any]) -> dict[str, Any]:
    response_type = value.get("type")
    if response_type == "tool_call":
        allowed = {"type", "call_id", "tool", "arguments"}
        if set(value) - allowed:
            raise ProtocolError(f"Unknown tool_call fields: {sorted(set(value) - allowed)}")
        if not isinstance(value.get("call_id"), str) or not _CALL_ID.fullmatch(
            value["call_id"]
        ):
            raise ProtocolError("tool_call requires a conservative unique call_id")
        if not isinstance(value.get("tool"), str) or not value["tool"]:
            raise ProtocolError("tool_call requires a tool name")
        if not isinstance(value.get("arguments"), dict):
            raise ProtocolError("tool_call arguments must be an object")
        return value
    if response_type == "final":
        allowed = {"type", "summary", "outputs", "verdict", "repair_patch"}
        if set(value) - allowed:
            raise ProtocolError(f"Unknown final fields: {sorted(set(value) - allowed)}")
        if not isinstance(value.get("summary"), str) or not value["summary"].strip():
            raise ProtocolError("final requires a non-empty summary")
        outputs = value.get("outputs", [])
        if not isinstance(outputs, list) or not all(
            isinstance(path, str) for path in outputs
        ):
            raise ProtocolError("final outputs must be an array of run-relative paths")
        try:
            value["outputs"] = [safe_run_path(path) for path in outputs]
        except PlanValidationError as exc:
            raise ProtocolError(str(exc)) from exc
        if "verdict" in value and value["verdict"] not in {"pass", "fail"}:
            raise ProtocolError("final verdict must be pass or fail")
        if "repair_patch" in value and not isinstance(value["repair_patch"], dict):
            raise ProtocolError("repair_patch must be an object")
        return value
    raise ProtocolError("Response type must be tool_call or final")


def parse_agent_response(text: str, *, done_reason: str | None = None) -> dict[str, Any]:
    return validate_agent_response(parse_json_object(text, done_reason=done_reason))
