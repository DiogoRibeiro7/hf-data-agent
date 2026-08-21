"""The orchestrator = the heart of the AGENT-API box.

Flow:
  1. retrieve company context from the pre-processed KB (offline arrow)
  2. assemble a grounded system prompt, including the tool catalogue
  3. run a bounded tool-calling loop against the open HF model (MODEL box)

The loop is deliberately bounded and deliberately forgiving. A model that never
asks for a tool simply answers, which is the original single-shot RAG path; a
model that asks for something impossible gets the error back as an observation
and can correct itself. Neither case can run away, because the number of tool
executions is capped by `DA_MAX_TOOL_STEPS`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from data_agent.datasources.sql_guard import UnsafeSQLError
from data_agent.knowledge.retriever import RetrievedContext
from data_agent.mcp.tools import TOOLS, ToolSpec
from data_agent.model.base import CONTEXT_MARKER, Message
from data_agent.model.streaming import stream_or_whole
from data_agent.orchestrator.tool_calls import ToolCall, parse_tool_call
from data_agent.runtime import Runtime

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are an internal data agent. Answer using the retrieved CONTEXT when "
    "relevant. If the context is insufficient, say so plainly. Be concise and "
    "cite sources by their [source] tag."
)

TOOL_PROTOCOL = (
    "You may call a tool to gather more information.\n"
    "To call one, reply with ONLY this JSON object and no other text:\n"
    '{"tool": "<tool name>", "args": {"<arg>": "<value>"}}\n'
    "You will then receive an OBSERVATION and may call another tool.\n"
    "When you can answer, reply with prose and no JSON.\n"
    "Never invent tool results; only use what an OBSERVATION gave you."
)

FINALISE = (
    "You have used the maximum number of tool calls. Answer now, using the "
    "observations above. If they are insufficient, say so plainly."
)


@dataclass
class ToolInvocation:
    """One executed tool call, kept so callers can see how an answer was reached."""

    tool: str
    args: dict[str, Any]
    #: What the model is shown. A failure needs detail here, or it cannot correct.
    result: str
    ok: bool
    #: What an external caller may be shown, when that differs. An adapter
    #: exception can carry a DSN, a filesystem path or the failing statement, and
    #: `steps` is serialised into /ask responses and SSE frames.
    client_result: str | None = None

    @property
    def shareable_result(self) -> str:
        """The result as it may leave the process."""
        return self.result if self.client_result is None else self.client_result


@dataclass
class AgentReply:
    answer: str
    contexts: list[RetrievedContext] = field(default_factory=list)
    steps: list[ToolInvocation] = field(default_factory=list)
    #: True when the loop ran out of budget and was forced to conclude.
    step_limit_reached: bool = False


@dataclass
class DeltaEvent:
    """A piece of the answer as it arrives."""

    text: str


@dataclass
class StepEvent:
    """A tool ran; the answer has not started yet."""

    step: ToolInvocation


@dataclass
class DoneEvent:
    """The turn is finished; carries the assembled reply."""

    reply: AgentReply


AgentEvent = DeltaEvent | StepEvent | DoneEvent

#: A turn that opens with one of these is a tool call, not prose, so its text is
#: withheld from the stream instead of leaking JSON into the answer.
_TOOL_CALL_OPENERS = ("{", "```")


def render_catalogue(specs: dict[str, ToolSpec]) -> str:
    lines = ["TOOLS:"]
    for spec in specs.values():
        lines.append(f"- {spec.signature()} — {spec.description}")
        for name, meaning in spec.parameters.items():
            lines.append(f"    {name}: {meaning}")
    return "\n".join(lines)


class Orchestrator:
    def __init__(self, runtime: Runtime, tools: dict[str, ToolSpec] | None = None) -> None:
        self.rt = runtime
        self.tools = TOOLS if tools is None else tools

    # ---------------------------------------------------------------- prompt --
    def _build_messages(self, question: str, contexts: list[RetrievedContext]) -> list[Message]:
        system = SYSTEM
        if self.rt.settings.enable_tools and self.tools:
            system = f"{system}\n\n{TOOL_PROTOCOL}\n\n{render_catalogue(self.tools)}"
        if contexts:
            blocks = "\n\n".join(f"[{c.source}]\n{c.text}" for c in contexts)
            system = f"{system}{CONTEXT_MARKER}{blocks}"
        return [Message("system", system), Message("user", question)]

    # ------------------------------------------------------------------ tools --
    def _execute(self, call: ToolCall) -> ToolInvocation:
        """Run a requested tool. Never raises: failures come back as observations
        so the model can correct itself rather than the request dying."""
        spec = self.tools.get(call.name)
        if spec is None:
            return ToolInvocation(
                tool=call.name,
                args=call.args,
                result=f"unknown tool {call.name!r}. Available: {', '.join(sorted(self.tools))}",
                ok=False,
            )

        missing = [arg for arg in spec.required if arg not in call.args]
        if missing:
            return ToolInvocation(
                tool=call.name,
                args=call.args,
                result=f"missing required argument(s): {', '.join(missing)}",
                ok=False,
            )

        try:
            output = spec.fn(self.rt, **call.args)
        except UnsafeSQLError as exc:
            # The guard describes the caller's own statement, so this is safe to
            # pass on as-is and genuinely useful to whoever sent it.
            logger.info("tool call rejected", extra={"tool": call.name})
            return ToolInvocation(call.name, call.args, f"UnsafeSQLError: {exc}", ok=False)
        except Exception as exc:
            # The model needs the detail; the caller gets the type only. Same
            # reasoning as the /tool route, which this path had been missing.
            logger.exception("tool call failed", extra={"tool": call.name})
            return ToolInvocation(
                call.name,
                call.args,
                f"{type(exc).__name__}: {exc}",
                ok=False,
                client_result=f"the tool failed ({type(exc).__name__})",
            )

        limit = self.rt.settings.tool_result_max_chars
        if len(output) > limit:
            output = output[:limit] + "\n… (result truncated)"
        return ToolInvocation(call.name, call.args, output, ok=True)

    def _observation(self, step: ToolInvocation) -> Message:
        if step.ok:
            body = f"OBSERVATION from {step.tool}:\n{step.result}"
        else:
            body = (
                f"ERROR from {step.tool}: {step.result}\n"
                "Correct the call, use a different tool, or answer without it."
            )
        return Message("user", body)

    # ----------------------------------------------------------------- answer --
    async def answer(self, question: str) -> AgentReply:
        started = time.perf_counter()
        contexts = self.rt.retriever.retrieve(question)
        logger.info(
            "retrieved context",
            extra={
                "question_chars": len(question),
                "contexts": len(contexts),
                "top_score": round(contexts[0].score, 4) if contexts else None,
            },
        )

        messages = self._build_messages(question, contexts)
        steps: list[ToolInvocation] = []
        settings = self.rt.settings

        if not settings.enable_tools or not self.tools:
            answer = await self.rt.model.generate(messages)
            return self._finish(answer, contexts, steps, False, started)

        for _ in range(max(settings.max_tool_steps, 0)):
            raw = await self.rt.model.generate(messages)
            call = parse_tool_call(raw)
            if call is None:
                # No tool requested: this turn is the answer.
                return self._finish(raw, contexts, steps, False, started)

            step = self._execute(call)
            steps.append(step)
            logger.info(
                "tool step",
                extra={"tool": step.tool, "ok": step.ok, "step": len(steps)},
            )
            messages.append(Message("assistant", raw))
            messages.append(self._observation(step))

        # Budget spent; ask once more, without leaving the tool door open.
        final = await self.rt.model.generate([*messages, Message("user", FINALISE)])
        return self._finish(final, contexts, steps, True, started)

    # ---------------------------------------------------------------- stream --
    async def _stream_turn(self, messages: list[Message]) -> AsyncIterator[DeltaEvent | _Turn]:
        """Run one model turn, yielding forwardable text and finally the turn."""
        turn = _Turn()
        async for chunk in stream_or_whole(self.rt.model, messages):
            forwardable = turn.add(chunk)
            if forwardable:
                yield DeltaEvent(forwardable)
        yield turn

    async def answer_stream(self, question: str) -> AsyncIterator[AgentEvent]:
        """The same loop as `answer`, emitted as it happens.

        Yields DeltaEvent as answer text arrives, StepEvent when a tool runs,
        and exactly one DoneEvent last carrying the assembled reply.
        """
        started = time.perf_counter()
        contexts = self.rt.retriever.retrieve(question)
        messages = self._build_messages(question, contexts)
        steps: list[ToolInvocation] = []
        settings = self.rt.settings
        rounds = max(settings.max_tool_steps, 0) if settings.enable_tools and self.tools else 0

        for _ in range(rounds):
            turn = None
            async for event in self._stream_turn(messages):
                if isinstance(event, DeltaEvent):
                    yield event
                else:
                    turn = event
            assert turn is not None

            call = parse_tool_call(turn.text)
            if call is None:
                # Prose after all. If it was withheld as a suspected tool call,
                # release it now so the answer is not silently truncated.
                withheld = turn.withheld()
                if withheld:
                    yield DeltaEvent(withheld)
                yield DoneEvent(self._finish(turn.text, contexts, steps, False, started))
                return

            step = self._execute(call)
            steps.append(step)
            yield StepEvent(step)
            messages.append(Message("assistant", turn.text))
            messages.append(self._observation(step))

        # Either tools are off, or the budget is spent: one final, tool-free turn.
        if rounds:
            messages = [*messages, Message("user", FINALISE)]
        final = None
        async for event in self._stream_turn(messages):
            if isinstance(event, DeltaEvent):
                yield event
            else:
                final = event
        assert final is not None
        withheld = final.withheld()
        if withheld:
            yield DeltaEvent(withheld)
        yield DoneEvent(self._finish(final.text, contexts, steps, bool(rounds), started))

    def _finish(
        self,
        answer: str,
        contexts: list[RetrievedContext],
        steps: list[ToolInvocation],
        limit_reached: bool,
        started: float,
    ) -> AgentReply:
        logger.info(
            "generated answer",
            extra={
                "backend": self.rt.settings.model_backend,
                "answer_chars": len(answer),
                "tool_steps": len(steps),
                "step_limit_reached": limit_reached,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return AgentReply(
            answer=answer,
            contexts=contexts,
            steps=steps,
            step_limit_reached=limit_reached,
        )


class _Turn:
    """Accumulates one streamed model turn and decides what may be forwarded.

    A turn is either prose (the answer) or a JSON tool call. Which one is not
    known until the first non-whitespace character arrives, so text is held back
    until then: a couple of characters of latency, in exchange for never
    emitting protocol noise into the answer.
    """

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.is_prose: bool | None = None

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def add(self, chunk: str) -> str | None:
        """Record `chunk`; return the text that may be forwarded, if any."""
        self.parts.append(chunk)
        if self.is_prose is False:
            return None
        if self.is_prose:
            return chunk

        opening = self.text.lstrip()
        if not opening:
            return None  # still only whitespace: undecided
        self.is_prose = not opening.startswith(_TOOL_CALL_OPENERS)
        return self.text if self.is_prose else None

    def withheld(self) -> str | None:
        """Text held back that turned out not to be a tool call after all."""
        return self.text if self.is_prose is False else None
