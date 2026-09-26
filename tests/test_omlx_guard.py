"""Run in .local/omlx-env to verify the pinned parser without loading weights."""

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@unittest.skipUnless(importlib.util.find_spec("omlx"), "requires the oMLX runtime environment")
class ToolGuardTests(unittest.TestCase):
    def test_unknown_call_reaches_codex_unchanged(self):
        self.check_call("read_stdin")

    def test_valid_call_is_not_duplicated(self):
        self.check_call("exec_command")

    def check_call(self, name):
        from omlx.adapter.output_parser import BailingHybridOutputParserSession
        from omlx_server import install_tool_guard

        original = BailingHybridOutputParserSession.finalize
        call = SimpleNamespace(id="bad-call", function=SimpleNamespace(name=name, arguments="{}"))
        session = BailingHybridOutputParserSession.__new__(BailingHybridOutputParserSession)
        session._detokenizer = None
        session._stream_filter = session._visible_filter = None
        session._tools = [{"type": "function", "function": {"name": "exec_command"}}]
        session._raw_text = "bad call"
        session._tokenizer = None
        with patch("omlx.api.tool_calling.parse_tool_calls", return_value=("", [call])):
            try:
                install_tool_guard()
                result = session.finalize()
                self.assertEqual(
                    result.tool_calls, [{"id": "bad-call", "name": name, "arguments": "{}"}]
                )
                self.assertEqual(result.finish_reason, "tool_calls")
            finally:
                BailingHybridOutputParserSession.finalize = original
