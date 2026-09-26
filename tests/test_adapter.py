import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from responses_adapter import response_items, translate


class AdapterTests(unittest.TestCase):
    def test_empty_completion_is_not_success(self):
        with self.assertRaisesRegex(ValueError, "no answer"):
            response_items({"content": "  ", "reasoning_content": "thinking"}, set())

    def test_developer_instructions_and_tool_result_survive(self):
        request, _ = translate(
            {
                "instructions": "First rule",
                "input": [
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": "Second rule"}],
                    },
                    {"role": "user", "content": "Read the file"},
                    {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call_1",
                        "arguments": '{"cmd":"cat proof.txt"}',
                    },
                    {"type": "function_call_output", "call_id": "call_1", "output": "fresh nonce"},
                ],
            }
        )
        self.assertEqual(
            request["messages"][0], {"role": "system", "content": "First rule\n\nSecond rule"}
        )
        self.assertEqual(
            request["messages"][-1],
            {"role": "tool", "tool_call_id": "call_1", "content": "fresh nonce"},
        )
        self.assertEqual(request["messages"][-2]["tool_calls"][0]["id"], "call_1")

    def test_custom_tool_round_trip(self):
        _, custom = translate(
            {
                "input": "Edit",
                "tools": [
                    {"type": "custom", "name": "apply_patch", "description": "Apply a patch"}
                ],
            }
        )
        output = response_items(
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_2",
                        "function": {
                            "name": "apply_patch",
                            "arguments": '{"input":"*** Begin Patch\\n*** End Patch"}',
                        },
                    }
                ],
            },
            custom,
        )
        self.assertEqual(output[0]["type"], "custom_tool_call")
        self.assertEqual(output[0]["input"], "*** Begin Patch\n*** End Patch")
        request, _ = translate(
            {
                "input": output
                + [{"type": "custom_tool_call_output", "call_id": "call_2", "output": "Success"}]
            }
        )
        self.assertEqual(request["messages"][-1]["content"], "Success")

    def test_rejects_unsupported_image(self):
        with self.assertRaisesRegex(ValueError, "Unsupported content"):
            translate(
                {
                    "input": [
                        {"role": "user", "content": [{"type": "input_image", "image_url": "x"}]}
                    ]
                }
            )

    def test_rejects_stateful_continuation(self):
        with self.assertRaisesRegex(ValueError, "full input history"):
            translate({"previous_response_id": "resp_old", "input": "Continue"})


if __name__ == "__main__":
    unittest.main()
