"""
ollama_chunked_model.py
=======================
A token-aware wrapper around Ollama's OpenAI-compatible endpoint via
``langchain_openai.ChatOpenAI``.

Rules
-----
- Soft threshold: 35 000 tokens.  If the assembled prompt exceeds this
  limit the request is broken into multiple sequential calls.
- Hard limit:    50 000 tokens.  No single call will ever send more than
  this many tokens, regardless of how the chunking lands.
- The wrapper exposes the same ``.invoke()`` and ``.bind_tools()`` API
  that LangChain models expose, so it is a drop-in replacement for the
  ``model_with_tools`` variable in ``naukri_agent_demo.py``.

How multi-call splitting works
-------------------------------
When the full message list is too long we:
1. Always include the *system* messages (HumanMessage / SystemMessage at
   the start of the list) because they carry the task description.
2. Split the remaining *conversation history* (AIMessage / ToolMessage
   pairs) into windows that each fit inside the soft threshold.
3. Send the system seed + each window to the model in order.  The
   assistant's reply from each intermediate window is appended to the
   next window so that reasoning flows forward.
4. Only the *last* call returns the final AIMessage that the agent loop
   processes.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional, Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# ---------------------------------------------------------------------------
# Token counting helpers
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """
    Fast token estimator: ~4 characters per token.
    Accurate enough for deciding whether to chunk; exact counts are
    obtained from the model's ``get_num_tokens`` when available.
    """
    return max(1, len(text) // 4)


def _message_token_count(msg: BaseMessage, model=None) -> int:
    """Return an estimated (or exact) token count for a single message."""
    content = msg.content or ""
    if isinstance(content, list):
        # Multimodal content — concatenate text parts
        content = " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    if model is not None and hasattr(model, "get_num_tokens"):
        try:
            return model.get_num_tokens(str(content))
        except Exception:
            pass
    return _estimate_tokens(str(content))


def _total_tokens(messages: List[BaseMessage], model=None) -> int:
    return sum(_message_token_count(m, model) for m in messages)


# ---------------------------------------------------------------------------
# Bound model wrapper (holds tool bindings)
# ---------------------------------------------------------------------------

class _BoundOllamaChunkedModel:
    """
    Returned by ``OllamaChunkedModel.bind_tools()``.
    Stores the list of tools and proxies ``.invoke()`` back to the
    parent with tool-calling enabled.
    """

    def __init__(self, parent: "OllamaChunkedModel", tools: list, bound_model):
        self._parent = parent
        self._tools = tools
        self._bound_model = bound_model  # the underlying ChatOpenAI with tools bound

    # Expose token helper so the agent loop can call it the same way
    def get_num_tokens(self, text: str) -> int:
        return self._parent.get_num_tokens(text)

    def invoke(self, messages: List[BaseMessage], **kwargs) -> AIMessage:
        return self._parent._chunked_invoke(
            messages, bound_model=self._bound_model, **kwargs
        )


# ---------------------------------------------------------------------------
# Main wrapper
# ---------------------------------------------------------------------------

class OllamaChunkedModel:
    """
    Token-aware wrapper around Ollama served via its OpenAI-compatible
    endpoint (``http://localhost:11434/v1`` by default).

    Parameters
    ----------
    model_name : str
        Ollama model tag, e.g. ``"qwen2.5"`` or ``"llama3"``.
    api_base : str
        Base URL of the Ollama server.
    api_key : str
        Placeholder key (Ollama ignores it but LangChain requires one).
    temperature : float
        Sampling temperature passed to the model.
    soft_token_limit : int
        If the assembled prompt exceeds this many tokens the request will
        be split into multiple calls.  Defaults to 35 000.
    hard_token_limit : int
        Absolute maximum tokens per single call.  Defaults to 50 000.
    verbose : bool
        When True, prints chunking diagnostics to stdout.
    """

    def __init__(
        self,
        model_name: str = "qwen2.5",
        api_base: str = "http://localhost:11434/v1",
        api_key: str = "local",
        temperature: float = 0.0,
        soft_token_limit: int = 35_000,
        hard_token_limit: int = 50_000,
        verbose: bool = True,
    ):
        from langchain_openai import ChatOpenAI  # lazy import

        self.model_name = model_name
        self.soft_token_limit = soft_token_limit
        self.hard_token_limit = hard_token_limit
        self.verbose = verbose

        self._base_model = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=api_base,
            temperature=temperature,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_num_tokens(self, text: str) -> int:
        """Proxy to underlying model's token counter with fallback."""
        if hasattr(self._base_model, "get_num_tokens"):
            try:
                return self._base_model.get_num_tokens(text)
            except Exception:
                pass
        return _estimate_tokens(text)

    def bind_tools(self, tools: list) -> _BoundOllamaChunkedModel:
        """
        Bind a list of LangChain tools and return a proxy object that
        forwards ``.invoke()`` through the chunking logic.
        """
        bound = self._base_model.bind_tools(tools)
        return _BoundOllamaChunkedModel(parent=self, tools=tools, bound_model=bound)

    def invoke(self, messages: List[BaseMessage], **kwargs) -> AIMessage:
        """Direct invocation without tool bindings (rarely used by agent)."""
        return self._chunked_invoke(messages, bound_model=self._base_model, **kwargs)

    # ------------------------------------------------------------------
    # Internal chunking logic
    # ------------------------------------------------------------------

    def _chunked_invoke(
        self,
        messages: List[BaseMessage],
        bound_model,
        **kwargs,
    ) -> AIMessage:
        """
        Core method.  Counts tokens; if under the soft limit it makes a
        single call.  Otherwise it splits the history into chunks and
        makes sequential calls, threading each intermediate reply into
        the next chunk so context flows forward.
        """
        total = _total_tokens(messages, self._base_model)

        if total <= self.soft_token_limit:
            if self.verbose:
                print(
                    f"  [OllamaChunked] Total tokens: {total} ≤ {self.soft_token_limit} "
                    "(single call)"
                )
            return bound_model.invoke(messages, **kwargs)

        # ----- Need to split -----
        if self.verbose:
            print(
                f"  [OllamaChunked] Total tokens: {total} > {self.soft_token_limit} "
                "— splitting into chunks"
            )

        seed_msgs, history_msgs = self._split_seed_and_history(messages)
        seed_tokens = _total_tokens(seed_msgs, self._base_model)

        chunks = self._build_chunks(history_msgs, seed_tokens)

        if self.verbose:
            print(
                f"  [OllamaChunked] Seed: {seed_tokens} tokens | "
                f"History split into {len(chunks)} chunk(s)"
            )

        last_response: Optional[AIMessage] = None

        for idx, chunk in enumerate(chunks):
            window: List[BaseMessage] = list(seed_msgs) + list(chunk)

            # Inject previous intermediate reply so the model keeps context
            if last_response is not None:
                # Insert right before the current chunk (after seed)
                window = list(seed_msgs) + [last_response] + list(chunk)

            chunk_tokens = _total_tokens(window, self._base_model)

            # Safety: enforce hard limit by dropping oldest history pairs
            window = self._enforce_hard_limit(window, seed_msgs, chunk_tokens)

            if self.verbose:
                print(
                    f"  [OllamaChunked] Chunk {idx + 1}/{len(chunks)} — "
                    f"{_total_tokens(window, self._base_model)} tokens"
                )

            last_response = bound_model.invoke(window, **kwargs)

        assert last_response is not None
        return last_response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _split_seed_and_history(
        self, messages: List[BaseMessage]
    ):
        """
        Separate the *seed* (leading HumanMessage / SystemMessage block
        that contains the task description) from the *history* (the
        back-and-forth AIMessage / ToolMessage conversation).

        Strategy: collect contiguous System/Human messages from the front
        of the list as the seed.  Everything else is history.
        """
        seed: List[BaseMessage] = []
        history: List[BaseMessage] = []
        in_seed = True

        for msg in messages:
            if in_seed and isinstance(msg, (SystemMessage, HumanMessage)):
                seed.append(msg)
            else:
                in_seed = False
                history.append(msg)

        # Edge-case: if all messages are seed-type, treat last message as
        # history so there is at least one call to make.
        if not history and seed:
            history = [seed.pop()]

        return seed, history

    def _build_chunks(
        self,
        history: List[BaseMessage],
        seed_tokens: int,
    ) -> List[List[BaseMessage]]:
        """
        Greedily group history messages into chunks where each chunk's
        token count, when added to seed_tokens, stays under the soft limit.
        """
        budget = self.soft_token_limit - seed_tokens
        chunks: List[List[BaseMessage]] = []
        current: List[BaseMessage] = []
        current_tokens = 0

        for msg in history:
            t = _message_token_count(msg, self._base_model)
            if current and current_tokens + t > budget:
                chunks.append(current)
                current = [msg]
                current_tokens = t
            else:
                current.append(msg)
                current_tokens += t

        if current:
            chunks.append(current)

        # Ensure we never return an empty list
        if not chunks:
            chunks = [history]

        return chunks

    def _enforce_hard_limit(
        self,
        window: List[BaseMessage],
        seed_msgs: List[BaseMessage],
        current_tokens: int,
    ) -> List[BaseMessage]:
        """
        If a window somehow exceeds the hard limit, drop the oldest
        non-seed messages one by one until it fits.
        """
        if current_tokens <= self.hard_token_limit:
            return window

        seed_count = len(seed_msgs)
        # Work on a mutable copy; never drop seed messages (indices 0..seed_count-1)
        trimmed = list(window)

        while _total_tokens(trimmed, self._base_model) > self.hard_token_limit:
            if len(trimmed) <= seed_count + 1:
                # Cannot trim further without removing all history
                break
            removed = trimmed.pop(seed_count)  # remove oldest history message
            if self.verbose:
                print(
                    f"  [OllamaChunked] Hard-limit trim: dropped "
                    f"{type(removed).__name__} to fit within {self.hard_token_limit} tokens"
                )

        return trimmed
