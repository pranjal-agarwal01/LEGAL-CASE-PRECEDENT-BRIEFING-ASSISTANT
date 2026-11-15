"""Chat-client factory and a structured-output helper on top of Agent Framework.

Every LLM-backed agent in this project is a `agent_framework.Agent` created from
the client returned by `build_chat_client`. `run_structured` asks the agent for a
pydantic-typed answer (provider-native structured output), and falls back to
parsing JSON out of plain text for providers or models that do not support it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from legal_brief.config import Settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

DEFAULT_MODELS = {"anthropic": "claude-opus-5-5"}


class LLMUnavailable(RuntimeError):
    pass


def build_chat_client(settings: Settings) -> Any | None:
    """Return an Agent Framework chat client for the configured provider (None = offline)."""
    p = settings.provider
    if p == "offline":
        return None
    model = settings.model or DEFAULT_MODELS.get(p, "")
    if not model:
        raise LLMUnavailable(f"Set LLM_MODEL for provider {p!r} (see .env.example).")
    if p == "foundry":
        return _foundry_client(settings, model)
    try:
        if p in ("openai", "azure_openai", "ollama"):
            from agent_framework.openai import OpenAIChatCompletionClient
        elif p == "anthropic":
            from agent_framework.anthropic import AnthropicClient
    except ImportError as e:  # connector package not installed
        pkg = "agent-framework-anthropic (pip install --pre ...)" if p == "anthropic" else "agent-framework-openai"
        raise LLMUnavailable(f"Provider {p!r} needs the {pkg} package: {e}") from e

    if p == "openai":
        if not settings.openai_api_key:
            raise LLMUnavailable("OPENAI_API_KEY is not set.")
        return OpenAIChatCompletionClient(model=model, api_key=settings.openai_api_key)
    if p == "azure_openai":
        if not (settings.azure_endpoint and settings.azure_api_key):
            raise LLMUnavailable("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set.")
        return OpenAIChatCompletionClient(model=model, api_key=settings.azure_api_key,
                                          azure_endpoint=settings.azure_endpoint,
                                          api_version=settings.azure_api_version)
    if p == "ollama":
        return OpenAIChatCompletionClient(model=model, base_url=settings.ollama_base_url, api_key="ollama")
    if p == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set.")
        return AnthropicClient(model=model, api_key=settings.anthropic_api_key)
    raise LLMUnavailable(f"Unknown provider {p!r}")


def is_claude_deployment(model: str, endpoint: str) -> bool:
    return model.lower().startswith("claude") or "/anthropic" in endpoint.lower()


def _foundry_client(settings: Settings, model: str) -> Any:
    """Microsoft Foundry: Claude deployments use the Anthropic Foundry client; every other
    deployment (GPT and other Foundry models) uses the Azure OpenAI chat-completions route."""
    endpoint, key = settings.foundry_endpoint.strip(), settings.foundry_api_key
    if not (endpoint and key):
        raise LLMUnavailable("Set FOUNDRY_ENDPOINT and FOUNDRY_API_KEY in .env (Foundry portal: your resource's "
                             "Keys and Endpoint page), and LLM_MODEL to your deployment name.")
    m = re.match(r"(https?://[^/]+)", endpoint)
    if not m:
        raise LLMUnavailable(f"FOUNDRY_ENDPOINT should look like https://<resource>.services.ai.azure.com, got {endpoint!r}")
    root = m.group(1)
    if is_claude_deployment(model, endpoint):
        try:
            from agent_framework.anthropic import AnthropicFoundryClient
        except ImportError as e:
            raise LLMUnavailable("Claude on Foundry needs: pip install --pre agent-framework-anthropic") from e
        host = root.split("//", 1)[1].split(".", 1)[0]
        base_url = f"https://{host}.services.ai.azure.com/anthropic/"
        return AnthropicFoundryClient(model=model, api_key=key, base_url=base_url)
    try:
        from agent_framework.openai import OpenAIChatCompletionClient
    except ImportError as e:
        raise LLMUnavailable("Foundry GPT deployments need: pip install agent-framework-openai") from e
    return OpenAIChatCompletionClient(model=model, api_key=key, azure_endpoint=root + "/",
                                      api_version=settings.foundry_api_version)


class _Ping(BaseModel):
    ok: bool
    reply: str


async def check_connection(settings: Settings) -> str:
    """One small structured-output request to confirm the provider, key and deployment work."""
    from agent_framework import Agent

    client = build_chat_client(settings)
    if client is None:
        return "offline mode: no LLM configured"
    agent = Agent(client, "You are a connectivity check. Answer briefly.", name="connection_check")
    out = await run_structured(agent, 'Return ok=true and reply="ready".', _Ping, max_tokens=200)
    return f"{type(client).__name__} -> ok={out.ok}, reply={out.reply!r}"


def extract_json(text: str) -> Any:
    """Pull the first JSON object out of a model reply (handles ```json fences)."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return json.loads(fence.group(1))
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object in reply")


async def run_structured(agent: Any, prompt: str, schema: type[T], max_tokens: int = 8000) -> T:
    """Run an Agent Framework agent and return a validated `schema` instance."""
    options = {"response_format": schema, "max_tokens": max_tokens}
    try:
        response = await agent.run(prompt, options=options)
    except (TypeError, ValueError) as e:  # provider rejected response_format: retry as plain text
        log.info("structured output not accepted (%s); retrying with JSON-in-text", e)
        response = await agent.run(
            prompt + "\n\nReply with a single JSON object that matches this JSON schema:\n"
            + json.dumps(schema.model_json_schema()), options={"max_tokens": max_tokens})
    try:  # `value` parses lazily and raises if the reply is not exactly one JSON object
        value = getattr(response, "value", None)
    except (ValueError, ValidationError):
        value = None
    if isinstance(value, schema):
        return value
    if isinstance(value, dict):
        return schema.model_validate(value)
    text = getattr(response, "text", "") or ""
    try:
        return schema.model_validate(extract_json(text))
    except (ValueError, ValidationError) as e:
        raise ValueError(f"Could not parse {schema.__name__} from model reply: {e}; reply starts {text[:200]!r}") from e
