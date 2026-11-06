"""Bridge Foundry Responses streaming to the existing Python tool loop."""

import httpx
from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletionChunk


class FoundryResponses:
    def __init__(self, client: AsyncOpenAI):
        self.client = client
        self._tool_outputs: dict[tuple[str, ...], list[dict]] = {}

    def clear(self):
        self._tool_outputs.clear()

    def _input(self, messages):
        items = []
        for message in messages:
            role = message["role"]
            content = message.get("content")
            if role == "tool":
                items.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": content or ""})
                continue
            calls = [call.model_dump() if hasattr(call, "model_dump") else call for call in message.get("tool_calls") or []]
            call_ids = tuple(call["id"] for call in calls)
            if call_ids in self._tool_outputs:
                # Preserve the reasoning items associated with function calls.
                items.extend(self._tool_outputs[call_ids])
                continue
            if content:
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if part["type"] == "text":
                            parts.append({"type": "input_text", "text": part["text"]})
                        elif part["type"] == "image_url":
                            parts.append({"type": "input_image", **part["image_url"], "image_url": part["image_url"]["url"]})
                            parts[-1].pop("url", None)
                    content = parts
                items.append({"role": role, "content": content})
            for call in calls:
                items.append({"type": "function_call", "call_id": call["id"], **call["function"]})
        return items

    async def create_stream(self, *, model, messages, tools, service_tier):
        stream = await self.client.responses.create(
            model=model,
            input=self._input(messages),
            tools=[{"type": "function", **tool["function"], "strict": False} for tool in tools],
            tool_choice="auto",
            stream=True,
            store=False,
            include=["reasoning.encrypted_content"],
            service_tier=service_tier,
        )
        return self._chunks(stream, model)

    async def _chunks(self, stream, model):
        response_id = "foundry-response"
        arguments: dict[int, str] = {}
        completed = False

        def chunk(delta, finish_reason=None):
            return ChatCompletionChunk(
                id=response_id,
                object="chat.completion.chunk",
                created=0,
                model=model,
                choices=[{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            )

        try:
            async for event in stream:
                if event.type == "response.created":
                    response_id = event.response.id
                elif event.type == "response.output_text.delta":
                    yield chunk({"content": event.delta})
                elif event.type == "response.refusal.delta":
                    yield chunk({"content": event.delta})
                elif event.type == "response.output_item.added" and event.item.type == "function_call":
                    item = event.item
                    arguments[event.output_index] = item.arguments or ""
                    yield chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": event.output_index,
                                    "id": item.call_id,
                                    "type": "function",
                                    "function": {"name": item.name, "arguments": item.arguments or ""},
                                }
                            ]
                        }
                    )
                elif event.type == "response.function_call_arguments.delta":
                    arguments[event.output_index] = arguments.get(event.output_index, "") + event.delta
                    yield chunk({"tool_calls": [{"index": event.output_index, "function": {"arguments": event.delta}}]})
                elif event.type == "response.function_call_arguments.done":
                    previous = arguments.get(event.output_index, "")
                    if event.arguments.startswith(previous) and len(event.arguments) > len(previous):
                        yield chunk(
                            {
                                "tool_calls": [
                                    {
                                        "index": event.output_index,
                                        "function": {"arguments": event.arguments[len(previous) :]},
                                    }
                                ]
                            }
                        )
                    arguments[event.output_index] = event.arguments
                elif event.type == "response.completed":
                    output = [item.model_dump(mode="json", exclude_none=True) for item in event.response.output]
                    call_ids = tuple(item["call_id"] for item in output if item["type"] == "function_call")
                    if call_ids:
                        self._tool_outputs[call_ids] = output
                    completed = True
                    yield chunk({}, "tool_calls" if call_ids else "stop")
                elif event.type in {"response.failed", "response.incomplete", "error"}:
                    error = getattr(getattr(event, "response", None), "error", None)
                    message = (
                        getattr(error, "message", None) or getattr(event, "message", None) or "Foundry response was incomplete."
                    )
                    raise APIError(message, request=httpx.Request("POST", str(self.client.base_url) + "responses"), body=None)
            if not completed:
                raise APIError(
                    "Foundry response stream ended before completion.",
                    request=httpx.Request("POST", str(self.client.base_url) + "responses"),
                    body=None,
                )
        finally:
            await stream.close()
