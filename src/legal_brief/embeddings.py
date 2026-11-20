"""Text embeddings for semantic search (Azure OpenAI / Microsoft Foundry or OpenAI).

Set EMBEDDING_MODEL to an embedding deployment (e.g. text-embedding-3-small). Without
one, retrieval uses BM25 keyword search (plus LSA on small libraries) and the
retrieval agent's own query reformulation and reranking.

Vectors are cached by a hash of (model, dims, text), so a library is embedded once.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)
MAX_CHARS = 6000
BATCH = 64


class EmbeddingCache(Protocol):
    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]: ...
    def put_many(self, items: dict[str, np.ndarray]) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._d: dict[str, np.ndarray] = {}

    def get_many(self, keys):
        return {k: self._d[k] for k in keys if k in self._d}

    def put_many(self, items):
        self._d.update(items)


class FileCache:
    """A .npz file of {key: float16 vector}; good for the shared library on a single server."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._d: dict[str, np.ndarray] = {}
        if self.path.exists():
            try:
                with np.load(self.path) as z:
                    self._d = {k: z[k] for k in z.files}
            except Exception as e:  # noqa: BLE001 - a corrupt cache is rebuilt
                log.warning("ignoring embedding cache %s: %s", self.path, e)

    def get_many(self, keys):
        return {k: self._d[k].astype(np.float32) for k in keys if k in self._d}

    def put_many(self, items):
        with self._lock:
            self._d.update({k: v.astype(np.float16) for k, v in items.items()})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp.npz")
            np.savez_compressed(tmp, **self._d)
            tmp.replace(self.path)


class Embedder:
    def __init__(self, client, model: str, dims: int | None, cache: EmbeddingCache | None = None):
        self.client, self.model, self.dims = client, model, dims
        self.cache = cache or MemoryCache()
        self._queries: OrderedDict[str, np.ndarray] = OrderedDict()

    def key(self, text: str) -> str:
        return hashlib.sha1(f"{self.model}|{self.dims}|{text[:MAX_CHARS]}".encode("utf-8")).hexdigest()

    def _call(self, texts: list[str]) -> np.ndarray:
        kwargs = {"model": self.model, "input": [t[:MAX_CHARS] or " " for t in texts]}
        if self.dims and re.search(r"embedding-3", self.model):
            kwargs["dimensions"] = self.dims
        resp = self.client.embeddings.create(**kwargs)
        m = np.array([d.embedding for d in sorted(resp.data, key=lambda d: d.index)], dtype=np.float32)
        return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-12)

    def embed(self, texts: list[str]) -> np.ndarray:
        keys = [self.key(t) for t in texts]
        have = self.cache.get_many(keys)
        missing = [i for i, k in enumerate(keys) if k not in have]
        for start in range(0, len(missing), BATCH):
            idx = missing[start:start + BATCH]
            vecs = self._call([texts[i] for i in idx])
            new = {keys[i]: v for i, v in zip(idx, vecs)}
            self.cache.put_many(new)
            have.update(new)
        return np.stack([have[k] for k in keys]) if keys else np.zeros((0, self.dims or 1), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        if text in self._queries:
            self._queries.move_to_end(text)
            return self._queries[text]
        v = self._call([text])[0]
        self._queries[text] = v
        if len(self._queries) > 512:
            self._queries.popitem(last=False)
        return v


def build_embedder(settings, cache: EmbeddingCache | None = None) -> Embedder | None:
    """Embedding client for the configured provider, or None when EMBEDDING_MODEL is unset."""
    model = settings.embedding_model
    if not model or settings.provider == "offline":
        return None
    try:
        if settings.provider == "foundry":
            from openai import AzureOpenAI

            root = re.match(r"(https?://[^/]+)", settings.foundry_endpoint.strip()).group(1)
            client = AzureOpenAI(api_key=settings.foundry_api_key, azure_endpoint=root + "/",
                                 api_version=settings.foundry_api_version)
        elif settings.provider == "azure_openai":
            from openai import AzureOpenAI

            client = AzureOpenAI(api_key=settings.azure_api_key, azure_endpoint=settings.azure_endpoint,
                                 api_version=settings.azure_api_version)
        elif settings.provider in ("openai", "ollama"):
            from openai import OpenAI

            client = (OpenAI(api_key=settings.openai_api_key) if settings.provider == "openai"
                      else OpenAI(base_url=settings.ollama_base_url, api_key="ollama"))
        else:
            return None
    except Exception as e:  # noqa: BLE001 - search still works without embeddings
        log.warning("embeddings unavailable: %s", e)
        return None
    return Embedder(client, model, settings.embedding_dims, cache)
