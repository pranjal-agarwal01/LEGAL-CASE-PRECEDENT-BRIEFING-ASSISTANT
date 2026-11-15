"""Hybrid retrieval over judgment passages: BM25 (lexical) + LSA (dense) + metadata.

* BM25 rewards exact legal vocabulary ("invitation to treat", "frustrated").
* LSA (truncated SVD over a TF-IDF matrix) gives a small dense embedding that
  matches paraphrases, without needing a model download or an API key.
* An optional doctrine boost adds a fixed amount to judgments tagged with the
  doctrine of the issue being researched (metadata-filtered RAG). Set it to 0
  for pure text retrieval; the evaluation reports both.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from legal_brief.corpus import Corpus, Passage

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
}


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


class HybridRetriever:
    def __init__(self, corpus: Corpus, *, k1: float = 1.5, b: float = 0.75, dims: int = 48,
                 bm25_weight: float = 0.6, doctrine_boost: float = 0.35):
        self.corpus = corpus
        self.k1, self.b = k1, b
        self.bm25_weight = bm25_weight
        self.doctrine_boost = doctrine_boost
        self.docs: list[Passage] = corpus.passages
        self._doc_tokens = [tokenize(self._doc_text(p)) for p in self.docs]
        self._build_bm25()
        self._build_lsa(dims)

    def _doc_text(self, p: Passage) -> str:
        j = self.corpus.get(p.judgment_id)
        return f"{j.name}. {j.area}. {p.text}" if j else p.text

    # ------------------------------------------------------------- BM25
    def _build_bm25(self) -> None:
        self._tf = [Counter(toks) for toks in self._doc_tokens]
        self._len = np.array([len(t) for t in self._doc_tokens], dtype=float)
        self._avgdl = float(self._len.mean()) if len(self._len) else 1.0
        df: Counter[str] = Counter()
        for toks in self._doc_tokens:
            df.update(set(toks))
        n = len(self.docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def _bm25_scores(self, q: list[str]) -> np.ndarray:
        scores = np.zeros(len(self.docs))
        for term in set(q):
            idf = self._idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self._tf):
                f = tf.get(term, 0)
                if f:
                    denom = f + self.k1 * (1 - self.b + self.b * self._len[i] / self._avgdl)
                    scores[i] += idf * f * (self.k1 + 1) / denom
        return scores

    # -------------------------------------------------------------- LSA
    def _build_lsa(self, dims: int) -> None:
        vocab = sorted(self._idf)
        self._vocab = {t: i for i, t in enumerate(vocab)}
        m = np.zeros((len(self.docs), len(vocab)))
        for i, tf in enumerate(self._tf):
            for t, f in tf.items():
                m[i, self._vocab[t]] = (1 + math.log(f)) * self._idf[t]
        m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-12)
        u, s, vt = np.linalg.svd(m, full_matrices=False)
        k = max(1, min(dims, len(s) - 1))
        self._vk = vt[:k].T  # vocab x k
        doc_vecs = m @ self._vk
        self._doc_vecs = doc_vecs / (np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-12)

    def _dense_scores(self, q: list[str]) -> np.ndarray:
        qv = np.zeros(len(self._vocab))
        for t, f in Counter(q).items():
            if t in self._vocab:
                qv[self._vocab[t]] = (1 + math.log(f)) * self._idf[t]
        if not qv.any():
            return np.zeros(len(self.docs))
        e = qv @ self._vk
        e = e / (np.linalg.norm(e) + 1e-12)
        return np.clip(self._doc_vecs @ e, 0.0, None)

    # ----------------------------------------------------------- search
    def search_passages(self, query: str, top_k: int = 10) -> list[PassageHit]:
        q = tokenize(query)
        bm, dn = self._bm25_scores(q), self._dense_scores(q)
        bm_n = bm / bm.max() if bm.max() > 0 else bm
        dn_n = dn / dn.max() if dn.max() > 0 else dn
        fused = self.bm25_weight * bm_n + (1 - self.bm25_weight) * dn_n
        order = np.argsort(-fused)[:top_k]
        return [
            PassageHit(self.docs[i].ref, self.docs[i].judgment_id, self.docs[i].pid,
                       float(fused[i]), float(bm_n[i]), float(dn_n[i]))
            for i in order if fused[i] > 0
        ]

    def search(self, query: str, top_k: int = 5, doctrine: str | None = None,
               doctrine_boost: float | None = None) -> list[JudgmentHit]:
        """Rank judgments: best passage score, plus the doctrine boost when tagged."""
        boost = self.doctrine_boost if doctrine_boost is None else doctrine_boost
        hits = self.search_passages(query, top_k=len(self.docs))
        grouped: dict[str, list[PassageHit]] = defaultdict(list)
        for h in hits:
            grouped[h.judgment_id].append(h)
        results = []
        for jid, phits in grouped.items():
            phits.sort(key=lambda h: -h.score)
            text_score = phits[0].score + 0.15 * sum(h.score for h in phits[1:3])
            j = self.corpus.get(jid)
            tagged = bool(doctrine and j and doctrine in j.doctrines)
            results.append(JudgmentHit(jid, text_score + (boost if tagged else 0.0), text_score, tagged, phits[:3]))
        results.sort(key=lambda r: (-r.score, r.judgment_id))
        return results[:top_k]
