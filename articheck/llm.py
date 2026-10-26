from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from urllib.parse import urljoin
from dataclasses import dataclass

from .runtime import Budget
from .trace import TraceWriter, validate_tokens


@dataclass
class ModelReply:
    text: str
    metadata: dict


class OpenAIPlannerClient:
    """Chat-compatible inference; native vLLM completion mode for trainable traces.

    No re-tokenization of response text is used to manufacture rollout tokens.
    API credentials are never included in traces.
    """
    def __init__(self, base_url: str, model: str, policy_version: str, native=False,
                 input_usd_per_million=0.0, output_usd_per_million=0.0):
        self.base_url = base_url.rstrip("/")
        self.model, self.policy_version, self.native = model, policy_version, native
        if min(input_usd_per_million, output_usd_per_million) < 0:
            raise ValueError("Token prices must be nonnegative")
        self.input_price, self.output_price = input_usd_per_million, output_usd_per_million
        self.key = os.environ.get("ARTICHECK_API_KEY", "EMPTY")

    def post(self, path: str, data: dict):
        url = urljoin(self.base_url + "/", path) if path.startswith("../") else self.base_url + path
        req = urllib.request.Request(url, json.dumps(data).encode(),
                                     {"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)

    async def complete(self, messages: list[dict], budget: Budget, trace: TraceWriter,
                       max_tokens=256, temperature=0.7) -> ModelReply:
        prompt_ids = None
        prompt = None
        if self.native:
            # base_url is /v1; vLLM /tokenize is a root-level endpoint.
            tokenized = await asyncio.to_thread(self.post, "../tokenize", {
                "model": self.model, "messages": messages, "add_generation_prompt": True})
            prompt_ids = tokenized["tokens"]
            prompt_bound = len(prompt_ids)
            prompt = prompt_ids
        else:
            # Conservative byte bound for supported byte/subword tokenizers, plus chat overhead.
            prompt_bound = len(json.dumps(messages, ensure_ascii=False).encode()) + 1024
        bound = prompt_bound + max_tokens
        cost_bound = (prompt_bound * self.input_price + max_tokens * self.output_price) / 1e6
        budget.reserve_model(bound, cost_bound)
        if self.native:
            body = {"model": self.model, "prompt": prompt, "max_tokens": max_tokens,
                    "temperature": temperature, "logprobs": 1, "return_token_ids": True,
                    "add_special_tokens": False}
            result = await asyncio.to_thread(self.post, "/completions", body)
        else:
            result = await asyncio.to_thread(self.post, "/chat/completions", {
                "model": self.model, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature})
        choice = result["choices"][0]
        text = choice["text"] if self.native else choice["message"]["content"]
        usage = result.get("usage", {})
        actual_prompt = usage.get("prompt_tokens", prompt_bound)
        actual_output = usage.get("completion_tokens", max_tokens)
        if actual_prompt > prompt_bound or actual_output > max_tokens:
            raise ValueError("Provider exceeded reserved token bound")
        budget.tokens -= bound - actual_prompt - actual_output
        actual_cost = (actual_prompt * self.input_price + actual_output * self.output_price) / 1e6
        budget.usd -= cost_bound - actual_cost
        row = {"role": "planner", "model": self.model, "policy_version": self.policy_version,
               "messages": messages, "text": text, "prompt_ids": prompt_ids,
               "response_ids": choice.get("token_ids"),
               "behavior_logprobs": (choice.get("logprobs") or {}).get("token_logprobs"),
               "token_source": "native" if self.native else "unavailable", "usage": usage,
               "finish_reason": choice.get("finish_reason"), "temperature": temperature}
        if self.native:
            validate_tokens(row)
        trace.write("model", **row)
        return ModelReply(text, row)
