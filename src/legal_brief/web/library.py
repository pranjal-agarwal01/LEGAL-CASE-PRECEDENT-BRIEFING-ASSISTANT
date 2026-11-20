"""Per-firm libraries: shared legislation and case summaries plus the firm's uploaded judgments."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from sqlalchemy import func, select

from legal_brief.config import Settings
from legal_brief.corpus import Corpus, Judgment, LibrarySpec, Passage, load_library
from legal_brief.embeddings import build_embedder
from legal_brief.retrieval import HybridRetriever
from legal_brief.web.db import Authority, DBEmbeddingCache, get_session

log = logging.getLogger(__name__)


def upload_id(authority_id: int) -> str:
    return f"U{authority_id}"


def authority_to_judgment(a: Authority) -> Judgment:
    year = int(a.date[:4]) if a.date[:4].isdigit() else 0
    passages = tuple(Passage(upload_id(a.id), p.pid, "paragraph", p.text, label=p.label) for p in a.passages)
    return Judgment(upload_id(a.id), a.name or a.filename, a.citation, a.court or "", year, a.area,
                    dict(a.doctrines or {}), passages, kind=a.kind if a.kind in ("judgment", "legislation") else "judgment",
                    url=a.url, date=a.date, summary=a.summary, source_note="Uploaded by your firm.",
                    jurisdiction=a.jurisdiction or "England and Wales")


class LibraryManager:
    def __init__(self, settings: Settings, max_cached: int = 6):
        self.settings = settings
        self.embedder = build_embedder(settings, DBEmbeddingCache())
        self._cache: OrderedDict[tuple, HybridRetriever] = OrderedDict()
        self._lock = threading.Lock()
        self.max_cached = max_cached

    @property
    def search_mode(self) -> str:
        return "semantic + keyword" if self.embedder else "keyword"

    def warm(self) -> None:
        """Embed the shared library once at startup (vectors are cached in the database), so the
        first brief after a deploy does not wait for it."""
        if not self.embedder:
            return
        try:
            base = self.base(True)
            probe = HybridRetriever(Corpus([]), embedder=None)  # reuse its document text format
            probe.corpus = base
            texts = [probe._doc_text(p) for p in base.passages]
            self.embedder.embed(texts)
            log.info("embedding cache warm: %d passages", len(texts))
        except Exception as e:  # noqa: BLE001 - search falls back to keywords
            log.warning("could not warm the embedding cache: %s", e)

    def base(self, include_summaries: bool) -> Corpus:
        return load_library(self.settings, LibrarySpec(summaries=include_summaries, legislation=True))

    def _version(self, firm_id: int) -> tuple:
        with get_session() as db:
            n, last = db.execute(select(func.count(Authority.id), func.max(Authority.id))
                                 .where(Authority.firm_id == firm_id, Authority.status == "ready")).one()
        return n, last

    def uploads(self, firm_id: int) -> Corpus:
        with get_session() as db:
            rows = db.execute(select(Authority).where(Authority.firm_id == firm_id, Authority.status == "ready")
                              ).scalars().all()
            return Corpus([authority_to_judgment(a) for a in rows if a.passages])

    def corpus(self, firm_id: int, include_summaries: bool) -> Corpus:
        return Corpus.merge(self.base(include_summaries), self.uploads(firm_id))

    def retriever(self, firm_id: int, include_summaries: bool, jurisdiction: str = "England and Wales") -> HybridRetriever:
        from legal_brief.jurisdiction import normalise

        jurisdiction = normalise(jurisdiction)
        key = (firm_id, include_summaries, jurisdiction, self._version(firm_id))
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        corpus = self.corpus(firm_id, include_summaries).for_jurisdiction(jurisdiction)
        r = HybridRetriever(corpus, doctrine_boost=self.settings.doctrine_boost, embedder=self.embedder)
        log.info("built library index for firm %s: %d authorities, %d passages (%s)",
                 firm_id, len(corpus), len(corpus.passages), r.dense_mode)
        with self._lock:
            for k in [k for k in self._cache if k[0] == firm_id and k[3] != key[3]]:
                del self._cache[k]  # older versions of this firm's library
            self._cache[key] = r
            while len(self._cache) > self.max_cached:
                self._cache.popitem(last=False)
        return r
