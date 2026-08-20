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
from dataclasses import dataclass, field
from typing import Any

from data_agent.knowledge.retriever import RetrievedContext
from data_agent.mcp.tools import TOOLS, ToolSpec
from data_agent.model.base import CONTEXT_MARKER, Message
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
    result: str
    ok: bool


@dataclass
class AgentReply:
    answer: str
    contexts: list[RetrievedContext] = field(default_factory=list)
    steps: list[ToolInvocation] = field(default_factory=list)
    #: True when the loop ran out of budget and was forced to conclude.
    step_limit_reached: bool = False


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
        except Exception as exc:  # surfaced to the model, not to the caller
            logger.info(
                "tool call failed",
                extra={"tool": call.name, "error": type(exc).__name__},
            )
            return ToolInvocation(call.name, call.args, f"{type(exc).__name__}: {exc}", ok=False)

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
