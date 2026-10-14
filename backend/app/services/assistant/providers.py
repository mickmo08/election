"""Provider-independent LLM layer.

Each provider implements `run(system, messages, tools, executor)` -> ProviderResult, running a
bounded tool-use loop where `executor(name, args)` executes read-only tools in backend code.
  * AnthropicProvider: official `anthropic` SDK (Claude), refusal handling, server-side fallbacks.
  * OpenAICompatibleProvider: any OpenAI-compatible chat-completions endpoint (non-Claude models).
  * OfflineProvider: deterministic planner/composer, no network; used when no LLM is configured
    and as the final fallback.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from ...config import get_settings

Executor = Callable[[str, dict], dict]


class ProviderError(Exception):
    pass


@dataclass
class ProviderResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    refused: bool = False


def tool_schemas(specs: dict) -> list[dict]:
    type_map = {"str": "string", "uuid": "string", "date": "string", "int": "integer"}
    out = []
    for name, spec in specs.items():
        props, required = {}, []
        for p, t in spec["params"].items():
            props[p] = {"type": type_map[t.rstrip("?")]}
            if not t.endswith("?"):
                required.append(p)
        out.append(
            {
                "name": name,
                "description": spec["description"],
                "input_schema": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        )
    return out


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        s = get_settings()
        if not s.anthropic_api_key:
            raise ProviderError("ELECTION_ANTHROPIC_API_KEY not configured")
        import anthropic  # noqa: PLC0415

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.llm_timeout_seconds, max_retries=1)
        self.model = s.anthropic_model

    def run(self, system: str, question: str, specs: dict, executor: Executor, max_calls: int) -> ProviderResult:
        s = get_settings()
        tools = [{**t, "strict": True} for t in tool_schemas(specs)]
        messages: list[dict] = [{"role": "user", "content": question}]
        res = ProviderResult("", self.name, self.model)
        deadline = time.monotonic() + s.llm_timeout_seconds * 2
        for _ in range(max_calls + 1):
            if time.monotonic() > deadline:
                raise ProviderError("assistant time budget exhausted")
            try:
                resp = self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=s.llm_max_output_tokens,
                    system=system,
                    messages=messages,
                    tools=tools,
                    tool_choice={"type": "auto"},
                    output_config={"effort": "medium"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            except self._anthropic.APIStatusError as exc:
                raise ProviderError(f"Anthropic API error {exc.status_code}") from exc
            except self._anthropic.APIConnectionError as exc:
                raise ProviderError("Anthropic API unreachable") from exc
            res.input_tokens += resp.usage.input_tokens
            res.output_tokens += resp.usage.output_tokens
            res.model = resp.model
            if resp.stop_reason == "refusal":
                res.refused = True
                return res
            # Append the full content (including thinking blocks) unchanged.
            messages.append({"role": "assistant", "content": resp.content})
            uses = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not uses:
                res.text = "".join(b.text for b in resp.content if b.type == "text")
                return res
            results = []
            for b in uses:
                if len(res.tool_calls) >= max_calls:
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": b.id,
                            "is_error": True,
                            "content": "tool call budget exhausted; answer with the evidence you have",
                        }
                    )
                    continue
                out = executor(b.name, dict(b.input))
                res.tool_calls.append({"name": b.name, "args": dict(b.input)})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out, default=str)})
            messages.append({"role": "user", "content": results})
        raise ProviderError("tool loop did not terminate")


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(self) -> None:
        s = get_settings()
        if not (s.openai_compatible_base_url and s.openai_compatible_model):
            raise ProviderError("OpenAI-compatible provider not configured")
        self.url = s.openai_compatible_base_url.rstrip("/") + "/chat/completions"
        self.key = s.openai_compatible_api_key
        self.model = s.openai_compatible_model

    def run(self, system: str, question: str, specs: dict, executor: Executor, max_calls: int) -> ProviderResult:
        s = get_settings()
        tools = [
            {
                "type": "function",
                "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
            }
            for t in tool_schemas(specs)
        ]
        messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        res = ProviderResult("", self.name, self.model)
        headers = {"authorization": f"Bearer {self.key}"} if self.key else {}
        with httpx.Client(timeout=s.llm_timeout_seconds) as client:
            for _ in range(max_calls + 1):
                try:
                    r = client.post(
                        self.url,
                        headers=headers,
                        json={
                            "model": self.model,
                            "messages": messages,
                            "tools": tools,
                            "max_tokens": s.llm_max_output_tokens,
                        },
                    )
                    r.raise_for_status()
                except httpx.HTTPError as exc:
                    raise ProviderError(f"provider request failed: {type(exc).__name__}") from exc
                body = r.json()
                usage = body.get("usage") or {}
                res.input_tokens += usage.get("prompt_tokens", 0)
                res.output_tokens += usage.get("completion_tokens", 0)
                msg = body["choices"][0]["message"]
                calls = msg.get("tool_calls") or []
                messages.append(msg)
                if not calls:
                    res.text = msg.get("content") or ""
                    return res
                for c in calls:
                    args = json.loads(c["function"]["arguments"] or "{}")
                    if len(res.tool_calls) >= max_calls:
                        out: dict = {"error": "tool call budget exhausted"}
                    else:
                        out = executor(c["function"]["name"], args)
                        res.tool_calls.append({"name": c["function"]["name"], "args": args})
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out, default=str)})
        raise ProviderError("tool loop did not terminate")


def build(name: str):  # type: ignore[no-untyped-def]
    if name == "anthropic":
        return AnthropicProvider()
    if name == "openai_compatible":
        return OpenAICompatibleProvider()
    return None  # offline is handled by the engine
