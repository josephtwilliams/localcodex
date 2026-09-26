"""Run pinned oMLX without silently discarding Ling's unknown tool calls."""


def install_tool_guard():
    from omlx.adapter.output_parser import BailingHybridOutputParserSession
    from omlx.api.tool_calling import parse_tool_calls

    original = BailingHybridOutputParserSession.finalize

    def finalize(self):
        result = original(self)
        if self._tools:
            _, calls = parse_tool_calls(self._raw_text, self._tokenizer, self._tools)
            # Preserve unknown names unchanged. Codex rejects them; never guess a tool.
            known = {
                tool["function"]["name"] for tool in self._tools if tool.get("type") == "function"
            }
            for call in calls or []:
                if call.function.name not in known:
                    result.tool_calls.append(
                        dict(id=call.id, name=call.function.name, arguments=call.function.arguments)
                    )
            if result.tool_calls:
                result.finish_reason = "tool_calls"
        return result

    BailingHybridOutputParserSession.finalize = finalize


if __name__ == "__main__":
    from omlx.cli import main

    install_tool_guard()
    main()
