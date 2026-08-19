"""The orchestrator = the heart of the AGENT-API box.

Default flow (retrieval-augmented generation):
  1. retrieve company context from the pre-processed KB (offline arrow)
  2. assemble a grounded system prompt
  3. call the open HF model (MODEL box, via the provider abstraction)

Live data tools (warehouse / airflow) are exposed both here and over MCP. A full
tool-calling / ReAct loop is the natural extension point — see prompts/.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from data_agent.knowledge.retriever import RetrievedContext
from data_agent.model.base import Message
from data_agent.runtime import Runtime

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
            system = f"{SYSTEM}\n\nCONTEXT:\n{blocks}"
        return [Message("system", system), Message("user", question)]

    async def answer(self, question: str) -> AgentReply:
        contexts = self.rt.retriever.retrieve(question)
        messages = self._build_messages(question, contexts)
        answer = await self.rt.model.generate(messages)
        return AgentReply(answer=answer, contexts=contexts)
