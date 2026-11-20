"""Hybrid retrieval over library passages: BM25 (lexical) + a dense signal + metadata.

* BM25 rewards exact legal vocabulary ("invitation to treat", "frustrated").
* The dense signal is a sentence embedding when EMBEDDING_MODEL is configured;
  otherwise, on small libraries, LSA (truncated SVD over a TF-IDF matrix) matches
  paraphrases without a model or an API key. Large libraries without embeddings
  use BM25 alone, plus the retrieval agent's own queries and reranking.
* An optional doctrine boost adds a fixed amount to authorities tagged with the
  doctrine of the issue being researched (metadata-filtered RAG). Set it to 0
  for pure text retrieval; the evaluation reports both.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from legal_brief.corpus import Corpus, Passage

log = logging.getLogger(__name__)

STOPWORDS = set(
    """a an and are as at be been but by for from had has have he her his i if in into is it its of on or our
    she so than that the their them then there these they this those to was we were what when where which who
    whom why will with would you your not no can could did do does done may might must shall should also
    about after again all any because before being both during each few further more most other over own same
    some such through under until up very just only once out off per s t mr mrs ms miss""".split()
)

SYNONYMS = {
    "advert": "advertisement", "ad": "advertisement", "ads": "advertisement",
    "ptsd": "psychiatric", "trauma": "psychiatric", "shock": "psychiatric",
    "warned": "warn", "warning": "warn", "consented": "consent",
    "cancelled": "cancel", "cancellation": "cancel", "hired": "hire", "hiring": "hire",
    "courier": "carrier", "couriers": "carrier", "parcel": "goods",
    "notice": "notice", "sign": "signed", "signature": "signed",
    "kombucha": "drink", "bottled": "bottle",
    "flat": "dwelling", "house": "dwelling", "home": "dwelling", "lessor": "landlord", "lessee": "tenant",
    "sacked": "dismissed", "fired": "dismissed", "boss": "employer", "staff": "employee",
}

LSA_MAX_PASSAGES = 1500  # above this, LSA's dense SVD costs too much memory; use embeddings instead


def _stem(tok: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "edly", "ed", "es", "ly", "s"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return tok


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z][a-z\-']*[a-z]|\d+", text.lower())
    out = []
    for t in toks:
        t = t.replace("'s", "").replace("'", "")
        if t in STOPWORDS or len(t) < 2:
            continue
        t = SYNONYMS.get(t, t)
        out.extend(_stem(p) for p in t.split("-") if p and p not in STOPWORDS)
    return out


@dataclass
class PassageHit:
    ref: str
    judgment_id: str
    pid: str
    score: float
    bm25: float
    dense: float
    similarity: float = 0.0  # raw cosine similarity to the query (embeddings only), for coverage checks


@dataclass
class JudgmentHit:
    judgment_id: str
    score: float
    text_score: float
    boosted: bool
    passages: list[PassageHit] = field(default_factory=list)

    @property
    def best_passage(self) -> str:
        return self.passages[0].ref if self.passages else f"{self.judgment_id}:p1"

    @property
    def similarity(self) -> float:
        return max((p.similarity for p in self.passages), default=0.0)


class HybridRetriever:
    """BM25 + a dense signal (embeddings when configured, else LSA on small libraries) + doctrine boost."""

    def __init__(self, corpus: Corpus, *, k1: float = 1.5, b: float = 0.75, dims: int = 48,
                 bm25_weight: float = 0.6, doctrine_boost: float = 0.35, embedder=None):
        self.corpus = corpus
        self.k1, self.b = k1, b
        self.bm25_weight = bm25_weight
        self.doctrine_boost = doctrine_boost
        self.embedder = embedder
        self.docs: list[Passage] = corpus.passages
        self._doc_tokens = [tokenize(self._doc_text(p)) for p in self.docs]
        self._build_bm25()
        self._doc_vecs = None
        self._vk = None
        self.dense_mode = "none"
        if embedder is not None and self.docs:
            try:
                self._doc_vecs = embedder.embed([self._doc_text(p) for p in self.docs])
                self.dense_mode = "embeddings"
            except Exception as e:  # noqa: BLE001 - fall back to keyword search
                log.warning("embedding the library failed (%s); using keyword search", e)
                self.embedder = None
        if self.dense_mode == "none" and 0 < len(self.docs) <= LSA_MAX_PASSAGES:
            self._build_lsa(dims)
            self.dense_mode = "lsa"

    def _doc_text(self, p: Passage) -> str:
        j = self.corpus.get(p.judgment_id)
        if not j:
            return p.text
        head = f"{j.name}, {p.display}" if j.is_legislation else f"{j.name}. {j.area}"
        return f"{head}. {p.text}"

    # ------------------------------------------------------------- BM25
    def _build_bm25(self) -> None:
        n = len(self.docs)
        self._len = np.array([len(t) for t in self._doc_tokens], dtype=float)
        self._avgdl = float(self._len.mean()) if n else 1.0
        postings: dict[str, dict[int, int]] = defaultdict(dict)
        for i, toks in enumerate(self._doc_tokens):
            for t, f in Counter(toks).items():
                postings[t][i] = f
        self._idf = {t: math.log(1 + (n - len(d) + 0.5) / (len(d) + 0.5)) for t, d in postings.items()}
        self._post = {t: (np.fromiter(d.keys(), dtype=np.int64), np.fromiter(d.values(), dtype=float))
                      for t, d in postings.items()}
        self._norm = self.k1 * (1 - self.b + self.b * self._len / self._avgdl) if n else np.zeros(0)

    def _bm25_scores(self, q: list[str]) -> np.ndarray:
        scores = np.zeros(len(self.docs))
        for term in set(q):
            post = self._post.get(term)
            if post is None:
                continue
            idx, tf = post
            scores[idx] += self._idf[term] * tf * (self.k1 + 1) / (tf + self._norm[idx])
        return scores

    # -------------------------------------------------------------- LSA
    def _build_lsa(self, dims: int) -> None:
        """Truncated SVD via the small n x n Gram matrix (float32): a few MB instead of a dense
        n x vocab SVD, so the index fits on a 512 MB server. Terms seen in one passage only are
        skipped; they cannot link paraphrases anyway."""
        n = len(self.docs)
        vocab = sorted(t for t, (idx, _) in self._post.items() if len(idx) >= 2 or n < 50)
        self._vocab = {t: i for i, t in enumerate(vocab)}
        m = np.zeros((n, len(vocab)), dtype=np.float32)
        for i, toks in enumerate(self._doc_tokens):
            for t, f in Counter(toks).items():
                j = self._vocab.get(t)
                if j is not None:
                    m[i, j] = (1 + math.log(f)) * self._idf[t]
        m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-12
        evals, evecs = np.linalg.eigh(m @ m.T)  # ascending
        k = max(1, min(dims, n - 1))
        evals, evecs = evals[::-1][:k], evecs[:, ::-1][:, :k]
        s = np.sqrt(np.clip(evals, 1e-12, None))
        self._vk = (m.T @ evecs) / s  # vocab x k, the right singular vectors
        doc_vecs = evecs * s  # = m @ vk
        self._doc_vecs = doc_vecs / (np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-12)

    def _dense_scores(self, query: str, q: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """(scores clipped at 0, raw cosine similarity; zeros unless embeddings are on)."""
        zero = np.zeros(len(self.docs))
        if self.dense_mode == "embeddings":
            try:
                sims = self._doc_vecs @ self.embedder.embed_query(query)
                return np.clip(sims, 0.0, None), sims
            except Exception as e:  # noqa: BLE001 - one failed query falls back to keywords
                log.warning("query embedding failed: %s", e)
                return zero, zero
        if self.dense_mode != "lsa":
            return zero, zero
        qv = np.zeros(len(self._vocab))
        for t, f in Counter(q).items():
            if t in self._vocab:
                qv[self._vocab[t]] = (1 + math.log(f)) * self._idf[t]
        if not qv.any():
            return zero, zero
        e = qv @ self._vk
        e = e / (np.linalg.norm(e) + 1e-12)
        return np.clip(self._doc_vecs @ e, 0.0, None), zero

    # ----------------------------------------------------------- search
    def search_passages(self, query: str, top_k: int = 10, only: str | None = None) -> list[PassageHit]:
        if not self.docs:
            return []
        q = tokenize(query)
        bm = self._bm25_scores(q)
        dn, sims = self._dense_scores(query, q)
        bm_n = bm / bm.max() if bm.max() > 0 else bm
        dn_n = dn / dn.max() if dn.max() > 0 else dn
        w = self.bm25_weight if self.dense_mode != "none" else 1.0
        fused = w * bm_n + (1 - w) * dn_n
        if only:
            mask = np.array([p.judgment_id == only for p in self.docs])
            fused = np.where(mask, fused + 1e-9, -1.0)
        order = np.argsort(-fused, kind="stable")[:top_k]
        return [
            PassageHit(self.docs[i].ref, self.docs[i].judgment_id, self.docs[i].pid,
                       float(fused[i]), float(bm_n[i]), float(dn_n[i]), float(sims[i]))
            for i in order if fused[i] > 0
        ]

    def best_passages(self, judgment_id: str, query: str, k: int = 3) -> list[str]:
        """The k passages of one authority that best match the query (for agent-picked authorities)."""
        hits = self.search_passages(query, top_k=k, only=judgment_id)
        if hits:
            return [h.ref for h in hits]
        j = self.corpus.get(judgment_id)
        return [j.key_passage().ref] if j else []

    def search(self, query: str, top_k: int = 5, doctrine: str | None = None,
               doctrine_boost: float | None = None, kinds: tuple[str, ...] | None = None) -> list[JudgmentHit]:
        """Rank authorities: best passage score, plus the doctrine boost when tagged."""
        boost = self.doctrine_boost if doctrine_boost is None else doctrine_boost
        hits = self.search_passages(query, top_k=len(self.docs))
        grouped: dict[str, list[PassageHit]] = defaultdict(list)
        for h in hits:
            grouped[h.judgment_id].append(h)
        results = []
        for jid, phits in grouped.items():
            j = self.corpus.get(jid)
            if kinds and j and j.kind not in kinds:
                continue
            phits.sort(key=lambda h: -h.score)
            text_score = phits[0].score + 0.15 * sum(h.score for h in phits[1:3])
            tagged = bool(doctrine and j and doctrine in j.doctrines)
            results.append(JudgmentHit(jid, text_score + (boost if tagged else 0.0), text_score, tagged, phits[:3]))
        results.sort(key=lambda r: (-r.score, r.judgment_id))
        return results[:top_k]
