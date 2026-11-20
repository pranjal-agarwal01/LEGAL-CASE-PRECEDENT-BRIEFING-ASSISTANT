"""Runtime settings, read from environment variables and an optional .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = ("offline", "foundry", "openai", "azure_openai", "anthropic", "ollama")


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines; existing environment variables win."""
    path = path or PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    provider: str = "offline"
    model: str = ""
    # Optional stronger model (same provider) for writing the brief and checking its sources.
    compiler_model: str = ""
    openai_api_key: str = ""
    azure_endpoint: str = ""
    azure_api_key: str = ""
    azure_api_version: str = "2024-10-21"
    anthropic_api_key: str = ""
    foundry_endpoint: str = ""
    foundry_api_key: str = ""
    foundry_api_version: str = "2024-10-21"
    ollama_base_url: str = "http://localhost:11434/v1"
    max_tokens: int = 8000
    debate_rounds: int = 2
    top_k: int = 5
    doctrine_boost: float = 0.35
    strict_llm: bool = False
    data_dir: Path = field(default=PROJECT_ROOT / "data")
    output_dir: Path = field(default=PROJECT_ROOT / "outputs")
    # Library: the CLI and evaluation default to the teaching summaries only; the web app adds legislation.
    include_summaries: bool = True
    include_legislation: bool = False
    # Embeddings (semantic search). Empty = keyword search plus model reranking.
    embedding_model: str = ""
    embedding_dims: int = 512
    # Source-support check: verify that cited passages actually support each claim (LLM mode).
    verify_support: bool = True

    @property
    def corpus_path(self) -> Path:
        return self.data_dir / "corpus" / "judgments.json"

    @property
    def legislation_path(self) -> Path:
        return self.data_dir / "library" / "legislation.json"

    @property
    def fact_sheet_dir(self) -> Path:
        return self.data_dir / "fact_sheets"

    @property
    def gold_path(self) -> Path:
        return self.data_dir / "eval" / "gold.json"

    @property
    def uses_llm(self) -> bool:
        return self.provider != "offline"

    def with_overrides(self, **kwargs) -> "Settings":
        clean = {k: v for k, v in kwargs.items() if v is not None}
        if "provider" in clean and clean["provider"] not in PROVIDERS:
            raise ValueError(f"Unknown provider {clean['provider']!r}; choose one of {PROVIDERS}")
        return replace(self, **clean)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        provider = _env("LLM_PROVIDER", "offline").lower() or "offline"
        if provider not in PROVIDERS:
            raise ValueError(f"LLM_PROVIDER={provider!r} is not one of {PROVIDERS}")
        return cls(
            provider=provider,
            model=_env("LLM_MODEL"),
            compiler_model=_env("COMPILER_MODEL"),
            openai_api_key=_env("OPENAI_API_KEY"),
            azure_endpoint=_env("AZURE_OPENAI_ENDPOINT"),
            azure_api_key=_env("AZURE_OPENAI_API_KEY"),
            azure_api_version=_env("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            foundry_endpoint=_env("FOUNDRY_ENDPOINT"),
            foundry_api_key=_env("FOUNDRY_API_KEY"),
            foundry_api_version=_env("FOUNDRY_API_VERSION", "2024-10-21"),
            ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            max_tokens=int(_env("LLM_MAX_TOKENS", "8000")),
            debate_rounds=int(_env("DEBATE_ROUNDS", "2")),
            top_k=int(_env("RETRIEVAL_TOP_K", "5")),
            doctrine_boost=float(_env("DOCTRINE_BOOST", "0.35")),
            strict_llm=_env("STRICT_LLM", "false").lower() in {"1", "true", "yes"},
            data_dir=Path(_env("LEGAL_BRIEF_DATA", str(PROJECT_ROOT / "data"))),
            output_dir=Path(_env("LEGAL_BRIEF_OUTPUT", str(PROJECT_ROOT / "outputs"))),
            include_summaries=_env("INCLUDE_SUMMARIES", "true").lower() in {"1", "true", "yes"},
            include_legislation=_env("INCLUDE_LEGISLATION", "false").lower() in {"1", "true", "yes"},
            embedding_model=_env("EMBEDDING_MODEL"),
            embedding_dims=int(_env("EMBEDDING_DIMS", "512")),
            verify_support=_env("VERIFY_SUPPORT", "true").lower() in {"1", "true", "yes"},
        )
