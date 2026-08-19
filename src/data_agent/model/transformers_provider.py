"""Run an open-weights HF model locally with transformers.

Install: pip install "hf-data-agent[transformers]"
Default model is small enough for CPU/modest GPU; point DA_MODEL_ID at any
instruct model (Qwen2.5, Llama-3.x, Phi-4, Mistral, ...).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from data_agent.config import Settings
from data_agent.model.base import Message


class TransformersProvider:
    def __init__(self, settings: Settings) -> None:
        import torch  # noqa: F401
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.settings = settings
        self.tokenizer = AutoTokenizer.from_pretrained(settings.model_id)
        self.model = AutoModelForCausalLM.from_pretrained(
            settings.model_id, torch_dtype="auto", device_map="auto"
        )

    def _generate_sync(self, messages: Sequence[Message]) -> str:
        prompt = self.tokenizer.apply_chat_template(
            [m.as_dict() for m in messages], tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        out = self.model.generate(
            **inputs,
            max_new_tokens=self.settings.model_max_new_tokens,
            temperature=self.settings.model_temperature,
            do_sample=self.settings.model_temperature > 0,
        )
        gen = out[0][inputs["input_ids"].shape[-1] :]
        decoded: str = self.tokenizer.decode(gen, skip_special_tokens=True)
        return decoded.strip()

    async def generate(self, messages: Sequence[Message]) -> str:
        # transformers is blocking; keep the event loop responsive.
        return await asyncio.to_thread(self._generate_sync, messages)
