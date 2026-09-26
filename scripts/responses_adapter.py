"""Local, stateless Responses-to-Chat adapter for text and Codex shell tools.

Buffers each upstream completion before emitting Responses events. This adds
first-visible-token latency, included in the Codex task timing.
Unsupported input types fail explicitly. No model downloads or external API calls.
"""

import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import BACKEND, MODEL, MODEL_PATH, api


def text_content(content):
    if isinstance(content, str):
        return content
    parts = []
    for part in content or []:
        if part.get("type") not in ("input_text", "output_text", "text"):
            raise ValueError(f"Unsupported content: {part.get('type')}")
        parts.append(part["text"])
    return "\n".join(parts)


def translate(body):
    if body.get("previous_response_id"):
        raise ValueError("Stateless adapter requires full input history")
    messages = []
    if body.get("instructions"):
        messages.append({"role": "system", "content": body["instructions"]})
    items = body.get("input", [])
    if isinstance(items, str):
        items = [{"role": "user", "content": items}]
    for item in items:
        kind = item.get("type", "message")
        if kind == "message":
            role = item["role"]
            messages.append(
                {
                    "role": "system" if role == "developer" else role,
                    "content": text_content(item.get("content")),
                }
            )
        elif kind in ("function_call", "custom_tool_call"):
            arguments = (
                item.get("arguments")
                if kind == "function_call"
                else json.dumps({"input": item["input"]})
            )
            call = {
                "id": item["call_id"],
                "type": "function",
                "function": {"name": item["name"], "arguments": arguments},
            }
            if messages and messages[-1]["role"] == "assistant" and messages[-1].get("tool_calls"):
                messages[-1]["tool_calls"].append(call)
            else:
                messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
        elif kind in ("function_call_output", "custom_tool_call_output"):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item["call_id"],
                    "content": text_content(item["output"]),
                }
            )
        elif kind == "reasoning":
            # Responses encrypted reasoning has no Chat Completions equivalent.
            if item.get("encrypted_content"):
                raise ValueError("Encrypted reasoning is unsupported")
        else:
            raise ValueError(f"Unsupported input item: {kind}")
    # Qwen's template accepts one initial system message, while Codex sends
    # instructions plus multiple developer messages. Preserve their order.
    system = [m["content"] for m in messages if m["role"] == "system"]
    messages = ([{"role": "system", "content": "\n\n".join(system)}] if system else []) + [
        m for m in messages if m["role"] != "system"
    ]
    tools, custom = [], set()
    for tool in body.get("tools", []):
        kind = tool["type"]
        if kind == "function":
            function = {k: tool[k] for k in ("name", "description", "parameters") if k in tool}
        elif kind == "custom":
            custom.add(tool["name"])
            function = {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": {"input": {"type": "string"}},
                    "required": ["input"],
                },
            }
        else:
            raise ValueError(f"Unsupported tool type: {kind}")
        tools.append({"type": "function", "function": function})
    request = {
        "model": MODEL if BACKEND in ("llama", "omlx", "rapid") else str(MODEL_PATH),
        "messages": messages,
        "stream": False,
        "seed": 0,
        "max_tokens": body.get("max_output_tokens", 2048),
        "temperature": body.get("temperature", 0),
    }
    if tools:
        request["tools"] = tools
    return request, custom


def response_items(message, custom):
    output = []
    if (message.get("content") or "").strip():
        output.append(
            {
                "id": "msg_" + uuid.uuid4().hex,
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": message["content"], "annotations": []}],
            }
        )
    for call in message.get("tool_calls") or []:
        f = call["function"]
        item = {
            "id": "fc_" + uuid.uuid4().hex,
            "call_id": call.get("id") or "call_" + uuid.uuid4().hex,
            "name": f["name"],
            "status": "completed",
        }
        if f["name"] in custom:
            item.update(type="custom_tool_call", input=json.loads(f["arguments"])["input"])
        else:
            item.update(type="function_call", arguments=f["arguments"])
        output.append(item)
    if not output:
        raise ValueError(
            "Model returned no answer or tool call; refusing an empty completion or compaction summary"
        )
    return output


class Handler(BaseHTTPRequestHandler):
    def json_reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.json_reply(
            200 if self.path == "/health" else 404,
            {"status": "ok" if self.path == "/health" else "not found"},
        )

    def do_POST(self):
        if self.path != "/v1/responses":
            return self.json_reply(404, {"error": "Only /v1/responses is supported"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            request, custom = translate(body)
            begin = time.perf_counter()
            completion = api("/v1/chat/completions", request)
            elapsed = time.perf_counter() - begin
            choice = completion["choices"][0]
            output = response_items(choice["message"], custom)
            usage = completion.get("usage", {})
            response = {
                "id": "resp_" + uuid.uuid4().hex,
                "object": "response",
                "created_at": int(time.time()),
                "status": "completed" if choice.get("finish_reason") != "length" else "incomplete",
                "model": body.get("model"),
                "output": output,
                "usage": {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
            if response["status"] == "incomplete":
                response["incomplete_details"] = {"reason": "max_output_tokens"}
            print(
                json.dumps(
                    {
                        "upstream_seconds": elapsed,
                        "usage": usage,
                        "output_types": [i["type"] for i in output],
                    }
                ),
                flush=True,
            )
            if not body.get("stream"):
                return self.json_reply(200, response)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            seq = 0

            def event(kind, **fields):
                nonlocal seq
                data = {"type": kind, "sequence_number": seq, **fields}
                seq += 1
                self.wfile.write(
                    ("event: " + kind + "\ndata: " + json.dumps(data) + "\n\n").encode()
                )
                self.wfile.flush()

            event("response.created", response={**response, "status": "in_progress", "output": []})
            for index, item in enumerate(output):
                empty = {**item, "status": "in_progress"}
                if item["type"] == "message":
                    empty["content"] = []
                elif item["type"] == "function_call":
                    empty["arguments"] = ""
                else:
                    empty["input"] = ""
                event("response.output_item.added", output_index=index, item=empty)
                if item["type"] == "message":
                    part = item["content"][0]
                    event(
                        "response.content_part.added",
                        output_index=index,
                        item_id=item["id"],
                        content_index=0,
                        part={**part, "text": ""},
                    )
                    event(
                        "response.output_text.delta",
                        output_index=index,
                        item_id=item["id"],
                        content_index=0,
                        delta=part["text"],
                    )
                    event(
                        "response.output_text.done",
                        output_index=index,
                        item_id=item["id"],
                        content_index=0,
                        text=part["text"],
                    )
                    event(
                        "response.content_part.done",
                        output_index=index,
                        item_id=item["id"],
                        content_index=0,
                        part=part,
                    )
                elif item["type"] == "function_call":
                    event(
                        "response.function_call_arguments.delta",
                        output_index=index,
                        item_id=item["id"],
                        delta=item["arguments"],
                    )
                    event(
                        "response.function_call_arguments.done",
                        output_index=index,
                        item_id=item["id"],
                        arguments=item["arguments"],
                    )
                else:
                    event(
                        "response.custom_tool_call_input.delta",
                        output_index=index,
                        item_id=item["id"],
                        delta=item["input"],
                    )
                    event(
                        "response.custom_tool_call_input.done",
                        output_index=index,
                        item_id=item["id"],
                        input=item["input"],
                    )
                event("response.output_item.done", output_index=index, item=item)
            event(
                "response.completed"
                if response["status"] == "completed"
                else "response.incomplete",
                response=response,
            )
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.json_reply(400, {"error": {"message": str(exc), "type": "adapter_error"}})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8092), Handler).serve_forever()
