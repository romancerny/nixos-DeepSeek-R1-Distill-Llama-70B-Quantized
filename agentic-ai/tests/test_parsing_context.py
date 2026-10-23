import unittest

from agentic_ai.context import build_messages, estimate_tokens
from agentic_ai.errors import ProtocolError
from agentic_ai.parsing import parse_agent_response, parse_json_object, strip_reasoning


class ParsingTests(unittest.TestCase):
    def test_strips_leading_deepseek_reasoning_blocks(self):
        raw = "<think>private reasoning</think>\n<thought>older tag</thought>\n{\"type\":\"final\",\"summary\":\"ok\"}"
        self.assertEqual(parse_agent_response(raw)["summary"], "ok")

    def test_unterminated_reasoning_and_length_are_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "Unterminated"):
            strip_reasoning("<think>unfinished")
        with self.assertRaisesRegex(ProtocolError, "truncated"):
            parse_json_object("{}", done_reason="length")

    def test_reasoning_literal_inside_json_is_preserved(self):
        value = parse_json_object('{"type":"final","summary":"Use <think> literally"}')
        self.assertEqual(value["summary"], "Use <think> literally")

    def test_markdown_and_non_object_json_are_rejected(self):
        with self.assertRaises(ProtocolError):
            parse_json_object('```json\n{"a": 1}\n```')
        with self.assertRaises(ProtocolError):
            parse_json_object("[]")

    def test_agent_schema_and_output_paths_are_validated(self):
        response = parse_agent_response(
            '{"type":"final","summary":"done","outputs":["workspace/a.py"]}'
        )
        self.assertEqual(response["outputs"], ["workspace/a.py"])
        with self.assertRaises(ProtocolError):
            parse_agent_response(
                '{"type":"final","summary":"bad","outputs":["../a.py"]}'
            )
        with self.assertRaises(ProtocolError):
            parse_agent_response(
                '{"type":"tool_call","call_id":"x","tool":"run_command","arguments":[]}'
            )


class ContextTests(unittest.TestCase):
    def test_compaction_retains_recent_failure_within_budget(self):
        history = [
            {"turn": 1, "kind": "tool_result", "content": "old" * 1000, "compact": "old summary"},
            {"turn": 2, "kind": "tool_result", "content": "older" * 1000, "compact": "older summary"},
            {"turn": 3, "kind": "external_feedback", "content": "LATEST FAILURE", "compact": "LATEST FAILURE"},
        ]
        messages = build_messages(
            system_prompt="system",
            task_prompt="task",
            history=history,
            context_length=220,
            num_predict=50,
            safety_reserve=10,
        )
        self.assertIn("LATEST FAILURE", messages[1]["content"])
        self.assertLessEqual(sum(estimate_tokens(item["content"]) for item in messages), 185)


if __name__ == "__main__":
    unittest.main()
