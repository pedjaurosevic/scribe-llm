"""
LLM Adapter - Connects to any llama-server endpoint.

Supports:
- Local llama-server (llama.cpp)
- Ollama
- LM Studio
- Any OpenAI-compatible API
"""

from __future__ import annotations

import os
import re
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from openai import OpenAI
from openai._streaming import Stream
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


class _ThinkSplitter:
    """
    Incrementally splits a streamed `content` field into ("thinking", text) and
    ("answer", text) events based on <think> ... </think> markers.

    Handles markers that arrive split across chunk boundaries by holding back a
    small tail that could still be the start of a marker.
    """

    def __init__(self) -> None:
        self.in_think = False
        self.buf = ""

    def _hold_partial(self, text: str, tag: str) -> tuple[str, str]:
        """Split text into (emit, hold) where hold is a possible tag prefix."""
        max_keep = min(len(tag) - 1, len(text))
        for k in range(max_keep, 0, -1):
            if tag.startswith(text[-k:]):
                return text[:-k], text[-k:]
        return text, ""

    def feed(self, text: str) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        self.buf += text

        while self.buf:
            if self.in_think:
                idx = self.buf.find(THINK_CLOSE)
                if idx == -1:
                    emit, self.buf = self._hold_partial(self.buf, THINK_CLOSE)
                    if emit:
                        events.append(("thinking", emit))
                    break
                if idx > 0:
                    events.append(("thinking", self.buf[:idx]))
                self.buf = self.buf[idx + len(THINK_CLOSE):]
                self.in_think = False
            else:
                idx = self.buf.find(THINK_OPEN)
                if idx == -1:
                    emit, self.buf = self._hold_partial(self.buf, THINK_OPEN)
                    if emit:
                        events.append(("answer", emit))
                    break
                if idx > 0:
                    events.append(("answer", self.buf[:idx]))
                self.buf = self.buf[idx + len(THINK_OPEN):]
                self.in_think = True

        return events

    def flush(self) -> list[tuple[str, str]]:
        """Emit any held-back remainder at end of stream."""
        if not self.buf:
            return []
        kind = "thinking" if self.in_think else "answer"
        events = [(kind, self.buf)]
        self.buf = ""
        return events


def parse_text_tool_calls(text: str) -> list[dict[str, Any]]:
    """
    Parse text-based tool calls (e.g. JSON blocks or ReAct style) from LLM output.
    """
    text_clean = text.strip()
    
    # 1. Try JSON parsing
    # Look for the first '{' and last '}'
    start_idx = text_clean.find("{")
    end_idx = text_clean.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_str = text_clean[start_idx:end_idx + 1]
        try:
            data = json.loads(json_str)
            if isinstance(data, dict):
                # Format: {"action": "...", "action_input": ...}
                if "action" in data:
                    name = data["action"]
                    args = data.get("action_input", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            pass
                    return [{
                        "id": "call_text_fallback",
                        "name": name,
                        "arguments": json.dumps(args) if isinstance(args, (dict, list)) else str(args)
                    }]
                # Format: {"name": "...", "arguments": ...}
                elif "name" in data and ("arguments" in data or "parameters" in data):
                    name = data["name"]
                    args = data.get("arguments") or data.get("parameters", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            pass
                    return [{
                        "id": "call_text_fallback",
                        "name": name,
                        "arguments": json.dumps(args) if isinstance(args, (dict, list)) else str(args)
                    }]
        except Exception:
            pass

    # 2. Try ReAct format parsing (e.g. Action: list_dir / Action Input: ...)
    action_match = re.search(r"(?:Action|Call):\s*([a-zA-Z0-9_-]+)", text_clean, re.IGNORECASE)
    if action_match:
        name = action_match.group(1).strip()
        # Find action input
        input_match = re.search(r"(?:Action Input|Arguments|Args|Input):\s*(.*)", text_clean, re.DOTALL | re.IGNORECASE)
        arguments = "{}"
        if input_match:
            args_str = input_match.group(1).strip()
            # Clean up wrap markdown
            if args_str.startswith("```"):
                # strip code fences
                lines = args_str.splitlines()
                if len(lines) >= 2:
                    args_str = "\n".join(lines[1:-1]).strip()
            arguments = args_str
        return [{
            "id": "call_text_fallback",
            "name": name,
            "arguments": arguments
        }]

    return []


class LLMAdapter:
    """
    Adapter for connecting to llama-server and similar OpenAI-compatible endpoints.

    Usage:
        adapter = LLMAdapter("http://127.0.0.1:18083/v1")
        response = adapter.complete([{"role": "user", "content": "Hello"}])
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str = "not-needed",
        model: str | None = None,
        timeout: int = 600,
        enable_thinking: bool = False,
    ):
        """
        Initialize the LLM adapter.

        Args:
            base_url: The base URL of the llama-server endpoint.
                     Defaults to SCRIBE_BASE_URL env var or http://127.0.0.1:18083/v1
            api_key: API key for authentication. Defaults to "not-needed" for llama.cpp
            model: Model name to use. If None, uses server default
            timeout: Request timeout in seconds
            enable_thinking: Ask the server to emit reasoning (llama.cpp gemma:
                sends a `chat_template_kwargs.enable_thinking` flag). Reasoning
                then arrives via the `reasoning_content` delta. Off by default so
                non-llama.cpp servers are not sent an unknown field.
        """
        self.base_url = base_url or os.environ.get(
            "SCRIBE_BASE_URL", "http://127.0.0.1:18083/v1"
        )
        self.api_key = api_key
        self.model = model or os.environ.get("SCRIBE_MODEL", "default")
        self.timeout = timeout
        self.enable_thinking = enable_thinking

        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
        )

    def _with_thinking(self, kwargs: dict) -> dict:
        """
        Inject the `enable_thinking` flag into the request body.

        The flag is sent both ways: True asks the server (llama.cpp/gemma) for
        native reasoning, False actively suppresses it (a real "no thinking"
        mode). An explicit value passed by the caller is respected.
        """
        extra_body = dict(kwargs.get("extra_body") or {})
        template_kwargs = dict(extra_body.get("chat_template_kwargs") or {})
        template_kwargs.setdefault("enable_thinking", bool(self.enable_thinking))
        extra_body["chat_template_kwargs"] = template_kwargs
        kwargs = dict(kwargs)
        kwargs["extra_body"] = extra_body
        return kwargs

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 1.0,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> str:
        """
        Send a completion request and return the response text.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            **kwargs: Additional arguments passed to the API

        Returns:
            The generated text response
        """
        kwargs = self._with_thinking(kwargs)
        response: ChatCompletion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 1.0,
        max_tokens: int | None = None,
        **kwargs,
    ):
        """
        Non-streaming completion that returns the full message object.

        Used for tool calling: the returned message may carry `tool_calls`
        (function calls the model wants executed) and/or `content`.

        Args:
            messages: Conversation so far
            tools: OpenAI-style tool schemas to advertise, or None
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional arguments

        Returns:
            The assistant ChatCompletionMessage.
        """
        kwargs = self._with_thinking(kwargs)
        if tools:
            kwargs["tools"] = tools
        response: ChatCompletion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return response.choices[0].message

    def streaming_complete(
        self,
        messages: list[dict[str, str]],
        callback=None,
        temperature: float = 1.0,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> Iterator[str]:
        """
        Send a streaming completion request.

        Args:
            messages: List of message dicts
            callback: Optional callback function called for each chunk
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            **kwargs: Additional arguments

        Yields:
            Text chunks as they arrive
        """
        kwargs = self._with_thinking(kwargs)
        stream: Stream[ChatCompletionChunk] = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
            stream=True,
            **kwargs,
        )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                if callback:
                    callback(text)
                yield text

    def streaming_events(
        self,
        messages: list[dict[str, str]],
        temperature: float = 1.0,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> Iterator[tuple[str, str]]:
        """
        Stream a completion split into reasoning and answer events.

        Yields (kind, text) tuples where kind is "thinking" or "answer".

        Reasoning is sourced from the server's `reasoning_content` delta field
        (e.g. llama.cpp with --reasoning-format) when present, and from inline
        <think> ... </think> markers in `content` as a fallback. Everything
        outside the thinking block is emitted as "answer".

        Args:
            messages: List of message dicts
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            **kwargs: Additional arguments

        Yields:
            (kind, text) tuples
        """
        kwargs = self._with_thinking(kwargs)
        stream: Stream[ChatCompletionChunk] = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
            stream=True,
            **kwargs,
        )

        splitter = _ThinkSplitter()

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield ("thinking", reasoning)

            if delta.content:
                yield from splitter.feed(delta.content)

        yield from splitter.flush()

    def streaming_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 1.0,
        max_tokens: int | None = None,
        **kwargs,
    ) -> Iterator[tuple[str, Any]]:
        """
        Stream one assistant turn, supporting reasoning, answer and tool calls.

        Yields (kind, payload) where kind is:
        - "thinking": payload is a reasoning text chunk
        - "answer":   payload is an answer text chunk
        - "tool_calls": payload is a list of accumulated calls (dicts with
          id/name/arguments) — emitted once at the end if the model requested any

        Tool-call fragments arrive piecemeal across chunks and are reassembled
        by index here.

        Args:
            messages: Conversation so far
            tools: OpenAI-style tool schemas to advertise, or None
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional arguments

        Yields:
            (kind, payload) tuples
        """
        kwargs = self._with_thinking(kwargs)
        if tools:
            kwargs["tools"] = tools

        stream: Stream[ChatCompletionChunk] = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )

        splitter = _ThinkSplitter()
        tool_acc: dict[int, dict[str, str]] = {}
        buffered_answer: list[str] = []
        is_json_candidate: bool | None = None # None = undecided, True = yes, False = no

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield ("thinking", reasoning)

            if delta.content:
                for kind, payload in splitter.feed(delta.content):
                    if kind == "answer":
                        if is_json_candidate is False:
                            yield (kind, payload)
                        else:
                            buffered_answer.append(payload)
                            if is_json_candidate is None:
                                full_buf = "".join(buffered_answer)
                                temp = full_buf.lstrip()
                                if temp:
                                    if temp.startswith("{") or temp.startswith("`"):
                                        is_json_candidate = True
                                    else:
                                        is_json_candidate = False
                                        yield (kind, full_buf)
                                        buffered_answer = []
                    else:
                        yield (kind, payload)

            for tc in (delta.tool_calls or []):
                slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        for kind, payload in splitter.flush():
            if kind == "answer":
                if is_json_candidate is False:
                    yield (kind, payload)
                else:
                    buffered_answer.append(payload)
                    if is_json_candidate is None:
                        full_buf = "".join(buffered_answer)
                        temp = full_buf.lstrip()
                        if temp:
                            if temp.startswith("{") or temp.startswith("`"):
                                is_json_candidate = True
                            else:
                                is_json_candidate = False
                                yield (kind, full_buf)
                                buffered_answer = []
            else:
                yield (kind, payload)

        if is_json_candidate is None and buffered_answer:
            yield ("answer", "".join(buffered_answer))
            buffered_answer = []

        if is_json_candidate is True and buffered_answer:
            full_text = "".join(buffered_answer)
            parsed_calls = parse_text_tool_calls(full_text)
            if parsed_calls:
                for idx, call in enumerate(parsed_calls):
                    tool_acc[idx] = call
            else:
                yield ("answer", full_text)

        if tool_acc:
            calls = [tool_acc[i] for i in sorted(tool_acc)]
            yield ("tool_calls", calls)

    def is_healthy(self) -> bool:
        """
        Check if the server is reachable.

        Returns:
            True if server responds, False otherwise
        """
        try:
            self.client.models.list()
            return True
        except Exception:
            return False

    def get_model_name(self) -> str:
        """
        Get the model name from the server.

        Returns:
            Model name string
        """
        try:
            models = self.client.models.list()
            if models.data:
                return models.data[0].id
        except Exception:
            pass
        return self.model

    async def streaming_complete_async(
        self,
        messages: list[dict[str, str]],
        temperature: float = 1.0,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """
        Async streaming completion for FastAPI WebSocket.

        Args:
            messages: List of message dicts
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            **kwargs: Additional arguments

        Yields:
            Text chunks as they arrive
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor()
        kwargs = self._with_thinking(kwargs)

        def sync_stream():
            stream: Stream[ChatCompletionChunk] = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                stream=True,
                **kwargs,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        def run_sync():
            return list(sync_stream())

        chunks = await loop.run_in_executor(executor, run_sync)
        for chunk in chunks:
            yield chunk

    async def streaming_events_async(
        self,
        messages: list[dict[str, str]],
        temperature: float = 1.0,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        **kwargs,
    ) -> AsyncIterator[tuple[str, str]]:
        """
        Async variant of streaming_events for FastAPI WebSocket.

        Yields (kind, text) tuples where kind is "thinking" or "answer".

        Args:
            messages: List of message dicts
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            **kwargs: Additional arguments

        Yields:
            (kind, text) tuples
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor()

        def run_sync():
            return list(
                self.streaming_events(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=stop,
                    **kwargs,
                )
            )

        events = await loop.run_in_executor(executor, run_sync)
        for event in events:
            yield event

    async def streaming_turn_async(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 1.0,
        max_tokens: int | None = None,
        **kwargs,
    ) -> AsyncIterator[tuple[str, Any]]:
        """
        Async variant of streaming_turn for FastAPI WebSocket.

        Yields (kind, payload) tuples: "thinking"/"answer" text chunks and a
        final "tool_calls" list when the model requested tool calls.

        Args:
            messages: Conversation so far
            tools: OpenAI-style tool schemas to advertise, or None
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional arguments

        Yields:
            (kind, payload) tuples
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor()

        def run_sync():
            return list(
                self.streaming_turn(
                    messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            )

        events = await loop.run_in_executor(executor, run_sync)
        for event in events:
            yield event
