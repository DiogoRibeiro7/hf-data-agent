"""The orchestrator = the heart of the AGENT-API box.

Default flow (retrieval-augmented generation):
  1. retrieve company context from the pre-processed KB (offline arrow)
  2. assemble a grounded system prompt
  3. call the open HF model (MODEL box, via the provider abstraction)

Live data tools (warehouse / airflow) are exposed both here and over MCP. A full
tool-calling / ReAct loop is the natural extension point.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from data_agent.knowledge.retriever import RetrievedContext
from data_agent.model.base import CONTEXT_MARKER, Message
from data_agent.runtime import Runtime

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are an internal data agent. Answer using the retrieved CONTEXT when "
    "relevant. If the context is insufficient, say so plainly. Be concise and "
    "cite sources by their [source] tag."
)


@dataclass
class AgentReply:
    answer: str
    contexts: list[RetrievedContext] = field(default_factory=list)


class Orchestrator:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    def _build_messages(self, question: str, contexts: list[RetrievedContext]) -> list[Message]:
        system = SYSTEM
        if contexts:
            blocks = "\n\n".join(f"[{c.source}]\n{c.text}" for c in contexts)
            system = f"{SYSTEM}{CONTEXT_MARKER}{blocks}"
        return [Message("system", system), Message("user", question)]

    async def answer(self, question: str) -> AgentReply:
        started = time.perf_counter()
        contexts = self.rt.retriever.retrieve(question)
        # The question itself may carry customer data, so only its shape is logged.
        logger.info(
            "retrieved context",
            extra={
                "question_chars": len(question),
                "contexts": len(contexts),
                "top_score": round(contexts[0].score, 4) if contexts else None,
            },
        )

        messages = self._build_messages(question, contexts)
        answer = await self.rt.model.generate(messages)
        logger.info(
            "generated answer",
            extra={
                "backend": self.rt.settings.model_backend,
                "answer_chars": len(answer),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return AgentReply(answer=answer, contexts=contexts)
