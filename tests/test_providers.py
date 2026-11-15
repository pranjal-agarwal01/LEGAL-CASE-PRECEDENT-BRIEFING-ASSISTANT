"""Provider wiring: building clients makes no network calls, so this runs offline."""

import pytest

from legal_brief.config import Settings
from legal_brief.llm import LLMUnavailable, build_chat_client


def _foundry(model: str, endpoint: str = "https://my-res.services.ai.azure.com/") -> Settings:
    return Settings(provider="foundry", model=model, foundry_endpoint=endpoint, foundry_api_key="test-key")


def test_foundry_gpt_deployment_uses_azure_openai_client():
    client = build_chat_client(_foundry("gpt-4.1"))
    assert type(client).__name__ == "OpenAIChatCompletionClient"


def test_foundry_claude_deployment_uses_anthropic_foundry_client():
    client = build_chat_client(_foundry("claude-sonnet-5-5", "https://my-res.openai.azure.com"))
    assert type(client).__name__ == "AnthropicFoundryClient"


def test_foundry_missing_settings_explain_what_to_set():
    with pytest.raises(LLMUnavailable, match="FOUNDRY_ENDPOINT"):
        build_chat_client(Settings(provider="foundry", model="gpt-4.1"))
    with pytest.raises(LLMUnavailable, match="LLM_MODEL"):
        build_chat_client(Settings(provider="foundry", foundry_endpoint="https://x.services.ai.azure.com", foundry_api_key="k"))
