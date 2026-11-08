"""The agent cassette: every call to a language model, kept, so a run can be played again with no model.

A hosted model does not repeat itself, even at temperature 0 with a seed (measured: 5 different answers in 5 identical calls).
So the answers are recorded instead. `CassetteModel` wraps a chat model: in `record` mode it calls the model and keeps the
request and the reply; in `replay` mode it answers from the cassette and never reaches the model; in `auto` mode it replays
what it has and records what it lacks. A request is identified by a hash of the role, the model, the messages (with the tool
results the agent has seen so far) and the tools offered, so a changed brief is a miss, never a wrong answer: a miss raises
`CassetteMiss`, the team's existing fallback takes over, and the timeline says so.

The file is a journal (see `brain.journal`): chained and sealed, so a doctored cassette is refused.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict

from brain.contracts.signing import canonical_json
from brain.journal import JournalWriter, read_journal


class CassetteMiss(LookupError):
    """The cassette has no recorded answer for this request."""


def _message_key(message: BaseMessage) -> dict[str, Any]:
    """A message without the ids LangChain generates, which differ on every run."""
    return {
        "type": message.type, "content": message.content, "name": getattr(message, "name", None),
        "tool_calls": [{"name": c["name"], "args": c["args"], "id": c.get("id")} for c in getattr(message, "tool_calls", None) or []],
        "tool_call_id": getattr(message, "tool_call_id", None),
    }


def request_hash(role: str, spec: str, messages: list[BaseMessage], offered: dict[str, Any]) -> str:
    body = {"role": role, "model": spec, "messages": [_message_key(m) for m in messages], "offered": offered}
    return hashlib.sha256(canonical_json(json.loads(json.dumps(body, default=str)))).hexdigest()[:20]


class Cassette:
    def __init__(self, path: str | Path, mode: str, secret: str | None = None) -> None:
        self.path, self.mode = Path(path), mode
        self.secret = secret if secret is not None else os.environ.get("BRAIN_HMAC_SECRET", "")
        self._calls: list[dict[str, Any]] = []
        self._header: dict[str, Any] = {"run_id": "cassette"}
        if self.path.exists() and mode != "record":
            journal = read_journal(self.path, self.secret)
            self._header, self._calls = journal.header, [r for r in journal.inputs if r["kind"] == "call"]
        self._queues: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for call in self._calls:
            self._queues[call["request_hash"]].append(call)

    def replay(self, key: str) -> dict[str, Any] | None:
        queue = self._queues.get(key)
        return queue.popleft()["reply"] if queue else None

    def record(self, role: str, spec: str, key: str, messages: list[BaseMessage], reply: BaseMessage, latency_ms: float) -> None:
        self._calls.append({
            "kind": "call", "role": role, "model": spec, "request_hash": key,
            "request": [message_to_dict(m) for m in messages], "reply": message_to_dict(reply),
            "usage": getattr(reply, "usage_metadata", None), "latency_ms": round(latency_ms, 1),
        })
        self._flush()

    def _flush(self) -> None:
        """Write the whole cassette again, sealed. It is small, and a cassette is then never half written."""
        writer = JournalWriter(self.path, {k: v for k, v in self._header.items() if k not in ("kind", "seq")}, self.secret)
        for call in self._calls:
            writer.append("call", **{k: v for k, v in call.items() if k not in ("kind", "seq")})
        writer.close()


class CassetteModel(BaseChatModel):
    """A chat model that records its inner model's answers or plays them back."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    inner: Any
    cassette: Any
    role: str
    spec: str

    @property
    def _llm_type(self) -> str:
        return "cassette"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        # The real model knows how its provider wants `tool_choice` and the tools written; in replay there is no real model.
        if self.inner is not None:
            return self.bind(**self.inner.bind_tools(tools, **kwargs).kwargs)
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], **kwargs)

    def _answer(self, messages: list[BaseMessage], kwargs: dict[str, Any]) -> tuple[str, ChatResult | None]:
        # Only the names of the tools offered: how a provider spells the same tool must not make a recording miss in replay.
        offered = {"tools": sorted(t.get("function", t).get("name", "") for t in kwargs.get("tools") or [])}
        key = request_hash(self.role, self.spec, messages, offered)
        if self.cassette.mode in ("replay", "auto"):
            reply = self.cassette.replay(key)
            if reply is not None:
                return key, ChatResult(generations=[ChatGeneration(message=messages_from_dict([reply])[0])])
        if self.cassette.mode == "replay":
            raise CassetteMiss(f"no recorded answer for the {self.role}'s request {key}: its brief or its tools changed since the recording")
        return key, None

    def _keep(self, messages: list[BaseMessage], key: str, result: ChatResult, started: float) -> ChatResult:
        self.cassette.record(self.role, self.spec, key, messages, result.generations[0].message, (time.monotonic() - started) * 1000)
        return result

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        key, hit = self._answer(messages, kwargs)
        if hit is not None:
            return hit
        started = time.monotonic()
        return self._keep(messages, key, self.inner._generate(messages, stop=stop, run_manager=run_manager, **kwargs), started)

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        key, hit = self._answer(messages, kwargs)
        if hit is not None:
            return hit
        started = time.monotonic()
        return self._keep(messages, key, await self.inner._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs), started)
