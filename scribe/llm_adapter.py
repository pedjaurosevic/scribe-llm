"""
LLM Adapter - Connects to any llama-server endpoint.

Supports:
- Local llama-server (llama.cpp)
- Ollama
- LM Studio
- Any OpenAI-compatible API
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import queue
import re
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
from openai import OpenAI
from openai._streaming import Stream
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from scribe.grammar import looks_like_tool_call, tool_call_grammar, validate_tool_call
from scribe.reasoning_gate import last_user_text, should_think

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


def _fallback_call(name: str, args: Any) -> dict[str, Any]:
    """Build a text-fallback tool call dict, normalizing arguments to a string."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            pass
    return {
        "id": "call_text_fallback",
        "name": name,
        "arguments": json.dumps(args) if isinstance(args, (dict, list)) else str(args),
    }


def parse_text_tool_calls(text: str) -> list[dict[str, Any]]:
    """
    Parse text-based tool calls (e.g. JSON blocks or ReAct style) from LLM output.
    """
    text_clean = text.strip()

    # 1. Try <|tool_call>call:tool_name{...} or call:tool_name{...} format (llama.cpp)
    if "call:" in text_clean.lower() or "<|tool_call>" in text_clean.lower():
        pat = r"(?:<\|tool_call\|?>\s*)?call:([a-zA-Z0-9_-]+)(.*?)$"
        match = re.search(pat, text_clean, re.DOTALL | re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            args_str = match.group(2).strip()
            s_idx = args_str.find("{")
            e_idx = args_str.rfind("}")
            if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
                args_str = args_str[s_idx:e_idx + 1]
            try:
                args = json.loads(args_str)
                return [_fallback_call(name, args)]
            except Exception:
                pass
            # Fix unquoted keys if present: {key: value} -> {"key": value}
            fixed_args = re.sub(r'([{\s,])([a-zA-Z0-9_-]+)\s*:', r'\1"\2":', args_str)
            try:
                args = json.loads(fixed_args)
                return [_fallback_call(name, args)]
            except Exception:
                pass
            try:
                args = ast.literal_eval(args_str)
                if isinstance(args, dict):
                    return [_fallback_call(name, args)]
            except Exception:
                pass

    # 2. Try JSON parsing
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
                    return [_fallback_call(data["action"], data.get("action_input", {}))]
                # Format: {"name": "...", "arguments": ...}
                elif "name" in data and ("arguments" in data or "parameters" in data):
                    args = data.get("arguments") or data.get("parameters", {})
                    return [_fallback_call(data["name"], args)]
        except Exception:
            pass

    # 3. Try ReAct format parsing (e.g. Action: list_dir / Action Input: ...)
    action_match = re.search(r"(?:Action|Call):\s*([a-zA-Z0-9_-]+)", text_clean, re.IGNORECASE)
    if action_match:
        name = action_match.group(1).strip()
        # Find action input
        input_match = re.search(
            r"(?:Action Input|Arguments|Args|Input):\s*(.*)",
            text_clean,
            re.DOTALL | re.IGNORECASE,
        )
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


class _AnswerGate:
    """
    Decides, while streaming, whether the answer channel carries prose (stream
    it through as it arrives) or a text-encoded tool call (capture it whole for
    parsing at end of stream).

    Models without native tool calling emit the call as a bare JSON object,
    sometimes wrapped in a markdown code fence. Only those two shapes are
    captured: a leading "{", or a fence whose first inner character is "{".
    Anything else — including answers that legitimately start with a code
    block — is released as soon as the gate can rule a tool call out, so prose
    is not held back for the whole turn.
    """

    def __init__(self) -> None:
        self._buf: list[str] = []
        self._streaming = False  # decided: prose, pass through
        self._capturing = False  # decided: JSON candidate, hold to the end

    def feed(self, text: str) -> list[str]:
        """Feed an answer chunk; return any text that is ready to stream out."""
        if self._streaming:
            return [text]
        self._buf.append(text)
        if self._capturing:
            return []

        verdict = self._sniff("".join(self._buf))
        if verdict is None:
            return []
        if verdict:
            self._capturing = True
            return []
        self._streaming = True
        out = "".join(self._buf)
        self._buf = []
        return [out]

    @staticmethod
    def _sniff(buf: str) -> bool | None:
        """True = JSON tool-call candidate, False = prose, None = need more."""
        head = buf.lstrip()
        if not head:
            return None
        if head.startswith("{"):
            return True

        potential_tags = ["<|tool_call", "call:"]
        for tag in potential_tags:
            if head.lower().startswith(tag):
                return True
            if tag.startswith(head.lower()):
                return None

        if head.startswith("`"):
            # Possibly a fenced tool call (```json\n{...}). Look past the
            # fence's opening line to see what it actually contains.
            newline = head.find("\n")
            if newline == -1:
                return None
            inner = head[newline + 1:].lstrip()
            if not inner:
                return None
            return inner.startswith("{")
        return False

    def flush(self) -> str:
        """Whatever is still buffered at end of stream."""
        out = "".join(self._buf)
        self._buf = []
        return out


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
        thinking_mode: str | None = None,
        tool_grammar: str = "auto",
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
            thinking_mode: "on" / "off" / "auto". "auto" runs the reasoning
                gate on the latest user message per request. When None, falls
                back to the boolean `enable_thinking`.
            tool_grammar: GBNF tool-call enforcement: "auto" repairs broken
                tool calls by re-asking with a grammar (llama.cpp only),
                "force" constrains every forced call, "off" disables.
        """
        self.base_url = base_url or os.environ.get(
            "SCRIBE_BASE_URL", "http://127.0.0.1:18083/v1"
        )
        self.api_key = api_key or "not-needed"
        self.model = model or os.environ.get("SCRIBE_MODEL", "default")
        self.timeout = timeout
        self.enable_thinking = enable_thinking
        if thinking_mode is None:
            thinking_mode = "on" if enable_thinking else "off"
        self.thinking_mode = thinking_mode
        self.tool_grammar = tool_grammar
        self.last_tool_repair: str | None = None  # set when grammar repaired a call
        self._grammar_supported: bool | None = None
        self._resolved_model: str | None = None

        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
        )

    @classmethod
    def from_config(cls, config) -> LLMAdapter:
        """
        Build an adapter from a ScribeConfig, wiring ALL connection settings
        (base_url, api_key, model, timeout, reasoning). Every entry point
        should use this so cloud endpoints with API keys work everywhere.
        """
        reasoning = config.reasoning
        if isinstance(reasoning, str):
            mode = reasoning.lower() if reasoning.lower() in ("auto", "on", "off") else "off"
        else:
            mode = "on" if reasoning else "off"
        return cls(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            timeout=config.request_timeout,
            enable_thinking=(mode == "on"),
            thinking_mode=mode,
            tool_grammar=getattr(config, "tool_grammar", "auto"),
        )

    def _request_model(self) -> str:
        """
        The model name sent with each request.

        llama.cpp ignores the field, so its conventional placeholder "default"
        is fine there — but Ollama and LM Studio reject unknown model names.
        When the configured model is the placeholder, resolve it once to the
        first model the server reports and cache it (only on success, so a
        temporarily unreachable server is retried next request).
        """
        if self.model and self.model != "default":
            return self.model
        if self._resolved_model:
            return self._resolved_model
        try:
            models = self.client.models.list()
            if models.data:
                self._resolved_model = models.data[0].id
                return self._resolved_model
        except Exception:
            pass
        return self.model

    def _with_thinking(self, kwargs: dict, messages: list[dict] | None = None) -> dict:
        """
        Inject the `enable_thinking` flag into the request body.

        The flag is sent both ways: True asks the server (llama.cpp/gemma) for
        native reasoning, False actively suppresses it (a real "no thinking"
        mode). In "auto" mode the reasoning gate decides per request from the
        latest user message. An explicit value passed by the caller is
        respected.
        """
        if self.thinking_mode == "auto":
            think = should_think(last_user_text(messages or []))
        else:
            think = self.thinking_mode == "on" or (
                self.thinking_mode not in ("on", "off") and bool(self.enable_thinking)
            )
        extra_body = dict(kwargs.get("extra_body") or {})
        template_kwargs = dict(extra_body.get("chat_template_kwargs") or {})
        template_kwargs.setdefault("enable_thinking", think)
        extra_body["chat_template_kwargs"] = template_kwargs
        kwargs = dict(kwargs)
        kwargs["extra_body"] = extra_body
        return kwargs

    def grammar_supported(self) -> bool:
        """
        Whether the server accepts a GBNF `grammar` request field.

        Only llama.cpp does; it is fingerprinted by its native /props endpoint
        (one cheap GET, cached for the adapter's lifetime).
        """
        if self._grammar_supported is None:
            props_url = self.base_url.rstrip("/").removesuffix("/v1") + "/props"
            try:
                r = httpx.get(props_url, timeout=3)
                self._grammar_supported = r.status_code == 200
            except Exception:
                self._grammar_supported = False
        return self._grammar_supported

    def forced_tool_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Ask for a tool call that *cannot* be malformed: the request carries a
        GBNF grammar derived from the tool schemas, so the only strings the
        model can produce are valid calls. Thinking is disabled for the
        request (the grammar constrains the whole output).

        Returns the parsed calls (one element). Raises if the server rejects
        the grammar — callers should check grammar_supported() first.
        """
        grammar = tool_call_grammar(tools)
        text = self.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={
                "grammar": grammar,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        calls = parse_text_tool_calls(text)
        if not calls:
            raise ValueError(f"grammar-constrained output did not parse: {text[:200]!r}")
        return calls

    def _repair_tool_calls(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        leftover: str,
    ) -> list[dict[str, Any]] | None:
        """
        The grammar-retry path: when a turn produced a broken tool call (bad
        JSON arguments, unknown tool, or an unparseable text blob that was
        clearly *trying* to be a call), re-ask once with the grammar attached.

        Returns repaired calls, or None when no repair is needed/possible.
        Sets `last_tool_repair` with a short reason when a repair ran.
        """
        self.last_tool_repair = None
        if self.tool_grammar == "off" or not tools:
            return None

        problem: str | None = None
        if calls:
            for call in calls:
                err = validate_tool_call(call, tools)
                if err:
                    problem = err
                    break
        elif leftover and looks_like_tool_call(leftover, tools):
            problem = "text tool call did not parse"

        if not problem or not self.grammar_supported():
            return None
        try:
            repaired = self.forced_tool_call(messages, tools)
        except Exception:
            return None
        self.last_tool_repair = problem
        return repaired

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
        kwargs = self._with_thinking(kwargs, messages)
        response: ChatCompletion = self.client.chat.completions.create(
            model=self._request_model(),
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
        kwargs = self._with_thinking(kwargs, messages)
        if tools:
            kwargs["tools"] = tools
        response: ChatCompletion = self.client.chat.completions.create(
            model=self._request_model(),
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
        kwargs = self._with_thinking(kwargs, messages)
        stream: Stream[ChatCompletionChunk] = self.client.chat.completions.create(
            model=self._request_model(),
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
        kwargs = self._with_thinking(kwargs, messages)
        stream: Stream[ChatCompletionChunk] = self.client.chat.completions.create(
            model=self._request_model(),
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
        kwargs = self._with_thinking(kwargs, messages)
        if tools:
            kwargs["tools"] = tools

        stream: Stream[ChatCompletionChunk] = self.client.chat.completions.create(
            model=self._request_model(),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )

        splitter = _ThinkSplitter()
        gate = _AnswerGate()
        tool_acc: dict[int, dict[str, str]] = {}

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
                        for text in gate.feed(payload):
                            yield ("answer", text)
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
                for text in gate.feed(payload):
                    yield ("answer", text)
            else:
                yield (kind, payload)

        # Anything still held by the gate is either a text-encoded tool call or
        # prose we could not rule out mid-stream — parse, else release as answer.
        leftover = gate.flush()
        unparsed = ""
        if leftover.strip():
            parsed_calls = parse_text_tool_calls(leftover)
            if parsed_calls:
                base = max(tool_acc) + 1 if tool_acc else 0
                for idx, call in enumerate(parsed_calls):
                    tool_acc[base + idx] = call
            else:
                unparsed = leftover

        calls = [tool_acc[i] for i in sorted(tool_acc)]

        # Grammar-retry: a broken call (bad arguments JSON, unknown tool, or a
        # text blob that tried to be a call) is re-asked once with the GBNF
        # grammar attached, making a second malformed answer impossible.
        repaired = self._repair_tool_calls(messages, tools or [], calls, unparsed)
        if repaired is not None:
            calls = repaired
            unparsed = ""

        if unparsed:
            yield ("answer", unparsed)
        if calls:
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

    async def _aiter_from_thread(
        self, make_iter: Callable[[], Iterator[Any]]
    ) -> AsyncIterator[Any]:
        """
        Run a sync streaming generator in a worker thread and yield its items
        as they are produced, so async callers (FastAPI WebSocket) get true
        incremental streaming instead of collect-then-replay.

        Producer errors are re-raised in the consumer. If the consumer stops
        early, the worker thread finishes draining the HTTP stream on its own
        (the OpenAI client closes it at end of iteration).
        """
        loop = asyncio.get_running_loop()
        items: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()

        def produce() -> None:
            try:
                for item in make_iter():
                    items.put(("item", item))
            except BaseException as exc:  # noqa: BLE001 - re-raised in consumer
                items.put(("error", exc))
            else:
                items.put(("end", None))

        loop.run_in_executor(None, produce)
        while True:
            kind, payload = await loop.run_in_executor(None, items.get)
            if kind == "item":
                yield payload
            elif kind == "error":
                raise payload
            else:
                return

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
        async for chunk in self._aiter_from_thread(
            lambda: self.streaming_complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                **kwargs,
            )
        ):
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

        Yields (kind, text) tuples where kind is "thinking" or "answer",
        as they arrive.

        Args:
            messages: List of message dicts
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            **kwargs: Additional arguments

        Yields:
            (kind, text) tuples
        """
        async for event in self._aiter_from_thread(
            lambda: self.streaming_events(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                **kwargs,
            )
        ):
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

        Yields (kind, payload) tuples as they arrive: "thinking"/"answer" text
        chunks and a final "tool_calls" list when the model requested tool calls.

        Args:
            messages: Conversation so far
            tools: OpenAI-style tool schemas to advertise, or None
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional arguments

        Yields:
            (kind, payload) tuples
        """
        async for event in self._aiter_from_thread(
            lambda: self.streaming_turn(
                messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        ):
            yield event
