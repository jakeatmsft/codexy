import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from openai import APIError
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from codexy.core.foundry import FoundryResponses


class EventStream:
    def __init__(self, events):
        self.events = events
        self.close = AsyncMock()

    async def __aiter__(self):
        for event in self.events:
            yield SimpleNamespace(**event)


class TestFoundryResponses(unittest.IsolatedAsyncioTestCase):
    async def test_tool_continuation_preserves_reasoning_and_native_call_id(self):
        reasoning = {"type": "reasoning", "id": "reasoning-1", "summary": [], "encrypted_content": "opaque"}
        function = {
            "type": "function_call",
            "id": "item-1",
            "call_id": "call-1",
            "name": "read_file",
            "arguments": '{"path":"file"}',
        }
        stream = EventStream(
            [
                {
                    "type": "response.output_item.added",
                    "output_index": 1,
                    "item": SimpleNamespace(**{**function, "arguments": ""}),
                },
                {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '{"path":'},
                {"type": "response.function_call_arguments.done", "output_index": 1, "arguments": function["arguments"]},
                {
                    "type": "response.completed",
                    "response": SimpleNamespace(
                        output=[
                            Mock(model_dump=Mock(return_value=reasoning)),
                            Mock(model_dump=Mock(return_value=function)),
                        ]
                    ),
                },
            ]
        )
        client = Mock(base_url="https://example.test/openai/v1/")
        client.responses.create = AsyncMock(return_value=stream)
        adapter = FoundryResponses(client)
        chunks = await adapter.create_stream(
            model="deployment", messages=[{"role": "user", "content": "Read file"}], tools=[], service_tier=NOT_GIVEN
        )
        received = [chunk async for chunk in chunks]
        assert received[-1].choices[0].finish_reason == "tool_calls"
        args = "".join(chunk.choices[0].delta.tool_calls[0].function.arguments or "" for chunk in received[:-1])
        assert args == function["arguments"]
        stream.close.assert_awaited_once()
        sent = client.responses.create.call_args.kwargs
        assert sent["store"] is False
        assert sent["include"] == ["reasoning.encrypted_content"]

        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    ChatCompletionMessageToolCall(
                        id="call-1", type="function", function=Function(name="read_file", arguments=args)
                    )
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
        ]
        assert adapter._input(messages) == [
            reasoning,
            function,
            {"type": "function_call_output", "call_id": "call-1", "output": "result"},
        ]
        adapter.clear()
        assert not adapter._tool_outputs

    async def test_incomplete_stream_reports_error_and_closes_connection(self):
        adapter = FoundryResponses(Mock(base_url="https://example.test/openai/v1/"))
        stream = EventStream([{"type": "response.output_text.delta", "delta": "partial"}])
        with self.assertRaisesRegex(APIError, "before completion"):
            _ = [chunk async for chunk in adapter._chunks(stream, "deployment")]
        stream.close.assert_awaited_once()

    async def test_failed_response_reports_service_error(self):
        adapter = FoundryResponses(Mock(base_url="https://example.test/openai/v1/"))
        stream = EventStream(
            [{"type": "response.failed", "response": SimpleNamespace(error=SimpleNamespace(message="deployment unavailable"))}]
        )
        with self.assertRaisesRegex(APIError, "deployment unavailable"):
            _ = [chunk async for chunk in adapter._chunks(stream, "deployment")]
        stream.close.assert_awaited_once()
