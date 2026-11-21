"""The searchable library, kept in the database instead of in memory.

Thousands of judgments do not fit in a 512 MB web server, so passages, their full-text index and their
embedding vectors live in the database and every search is a query:

* Postgres (Render): a generated `tsvector` column with a GIN index for keyword search, and a pgvector
  column (`halfvec`, or `vector` on older pgvector) with an HNSW index for semantic search.
* SQLite (local development and tests): an FTS5 table for keywords and float16 vectors in a BLOB column,
  compared in memory.

`DBCorpus` and `DBRetriever` offer the same interface as `Corpus` and `HybridRetriever`, so the agents,
citation checks and source check work unchanged. Authorities are loaded on demand and cached.
"""

from __future__ import annotations

import logging
import re
import threading
import urllib.request
from collections import OrderedDict, defaultdict
from pathlib import Path

import numpy as np
from sqlalchemy import delete, func, select, text

from legal_brief.corpus import Judgment, Passage, _act_key, _name_key
from legal_brief.library_file import SEED_FORMAT, read_seed, seed_to_authority, write_seed  # noqa: F401
from legal_brief.retrieval.index import STOPWORDS, JudgmentHit, PassageHit
from legal_brief.web.db import LibAuthority, LibPassage, get_session

log = logging.getLogger(__name__)

CANDIDATES = 200  # passages fetched from each of the keyword and vector indexes before fusing
HEADNOTE_WEIGHT = 0.8  # editorial headnotes rank below the judgment's own paragraphs


def doc_text(name: str, kind: str, area: str, label: str, body: str) -> str:
    """The text that is embedded and searched: the authority's name gives every passage its context."""
    head = f"{name}, {label}" if kind == "legislation" else f"{name}. {area}"
    return f"{head}. {body}"


def name_key(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def _query_words(query: str, limit: int = 40) -> list[str]:
    words = []
    for w in re.findall(r"[a-z][a-z0-9]+|\d+[a-z]?", query.lower()):
        if w not in STOPWORDS and len(w) > 1 and w not in words:
            words.append(w)
    return words[:limit]


class LibraryStore:
    """Schema, loading and queries for the library tables (one per process)."""

    def __init__(self, engine, embedder=None, dims: int = 512):
        self.engine = engine
        self.embedder = embedder
        self.dims = dims
        self.pg = engine.dialect.name == "postgresql"
        self.vec_type: str | None = None  # halfvec | vector | None (no pgvector)
        self.pgvector: tuple[int, int] = (0, 0)
        self.version = 0  # bumped whenever the library changes; caches compare against it
        self._lock = threading.Lock()
        self._mem: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}  # SQLite vectors per (firm, jurisdiction)
        self.last_header: dict = {}

    # ------------------------------------------------------------------ schema
    def setup(self) -> None:
        if self.pg:
            self._setup_pg()
        else:
            with self.engine.begin() as c:
                c.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS lib_passages_fts "
                               "USING fts5(body, tokenize='porter unicode61')"))

    def _setup_pg(self) -> None:
        with self.engine.begin() as c:
            c.execute(text(
                "ALTER TABLE lib_passages ADD COLUMN IF NOT EXISTS tsv tsvector GENERATED ALWAYS AS "
                "(to_tsvector('english', coalesce(title, '') || ' ' || text)) STORED"))
            c.execute(text("CREATE INDEX IF NOT EXISTS lib_passages_tsv ON lib_passages USING gin (tsv)"))
        try:
            with self.engine.begin() as c:
                c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                ver = c.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
        except Exception as e:  # noqa: BLE001 - keyword search still works
            log.warning("pgvector is not available (%s); semantic search is off", e)
            return
        major, minor = (int(x) for x in (ver or "0.0").split(".")[:2])
        self.pgvector = (major, minor)
        self.vec_type = "halfvec" if (major, minor) >= (0, 7) else "vector"
        ops = f"{self.vec_type}_cosine_ops"
        with self.engine.begin() as c:
            c.execute(text(f"ALTER TABLE lib_passages ADD COLUMN IF NOT EXISTS vec {self.vec_type}({self.dims})"))
            c.execute(text(f"CREATE INDEX IF NOT EXISTS lib_passages_vec ON lib_passages USING hnsw (vec {ops})"))
        log.info("library search: Postgres full-text + pgvector %s (%s)", ver, self.vec_type)

    @property
    def dense_mode(self) -> str:
        if not self.embedder:
            return "none"
        return "embeddings" if (self.vec_type or not self.pg) else "none"

    # ------------------------------------------------------------------ writing
    def count(self, firm_id: int | None = None) -> int:
        with get_session() as db:
            q = select(func.count(LibAuthority.id))
            q = q.where(LibAuthority.firm_id.is_(None)) if firm_id is None else q.where(LibAuthority.firm_id == firm_id)
            return db.execute(q).scalar_one()

    def add(self, j: Judgment, firm_id: int | None = None, vectors: np.ndarray | None = None,
            embed: bool = True) -> None:
        """Insert (or replace) one authority with its passages, embedding them when no vectors are given."""
        texts = [doc_text(j.name, j.kind, j.area, p.display, p.text) for p in j.passages]
        if vectors is None and embed and self.embedder is not None and texts:
            try:
                vectors = self.embedder.embed(texts)
            except Exception as e:  # noqa: BLE001 - keyword search still finds it
                log.warning("could not embed %s: %s", j.id, e)
        self.add_many([(j, firm_id, vectors)])

    def add_many(self, items: list[tuple[Judgment, int | None, np.ndarray | None]]) -> None:
        with get_session() as db:
            ids = [j.id for j, _, _ in items]
            self._delete_ids(db, ids)
            for j, firm_id, _ in items:
                db.add(LibAuthority(
                    id=j.id, firm_id=firm_id, kind=j.kind, name=j.name[:400], name_key=name_key(j.name)[:400],
                    citation=j.citation[:200], court=j.court[:120], year=j.year, date=j.date, area=j.area[:80],
                    jurisdiction=j.jurisdiction, doctrines=dict(j.doctrines), url=j.url[:500], summary=j.summary,
                    source_note=j.source_note, n_passages=len(j.passages)))
            db.flush()
            for j, firm_id, vecs in items:
                rows = []
                for i, p in enumerate(j.passages):
                    v = None if vecs is None else np.asarray(vecs[i], dtype=np.float16)
                    rows.append({"authority_id": j.id, "firm_id": firm_id, "seq": i, "pid": p.pid,
                                 "section": p.section, "label": p.label, "title": p.title[:400], "text": p.text,
                                 "embedding": None if (v is None or self.pg) else v.tobytes(), "_v": v})
                self._insert_passages(db, rows)
            db.commit()
        self._changed()

    def _insert_passages(self, db, rows: list[dict]) -> None:
        if not rows:
            return
        cols = ["authority_id", "firm_id", "seq", "pid", "section", "label", "title", "text", "embedding"]
        if self.pg and self.vec_type:
            sql = text(f"INSERT INTO lib_passages ({', '.join(cols)}, vec) VALUES "
                       f"({', '.join(':' + c for c in cols)}, CAST(:vec AS {self.vec_type}))")
            db.execute(sql, [{**{c: r[c] for c in cols},
                              "vec": None if r["_v"] is None else _vec_literal(r["_v"])} for r in rows])
            return
        db.execute(text(f"INSERT INTO lib_passages ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"),
                   [{c: r[c] for c in cols} for r in rows])
        if not self.pg:
            aid = rows[0]["authority_id"]
            for pid_, body in db.execute(text("SELECT id, coalesce(title, '') || ' ' || text FROM lib_passages "
                                              "WHERE authority_id = :a"), {"a": aid}):
                db.execute(text("INSERT INTO lib_passages_fts (rowid, body) VALUES (:i, :b)"), {"i": pid_, "b": body})

    def _delete_ids(self, db, ids: list[str]) -> None:
        if not ids:
            return
        if not self.pg:
            db.execute(text("DELETE FROM lib_passages_fts WHERE rowid IN (SELECT id FROM lib_passages "
                            "WHERE authority_id IN (" + ",".join(f":i{n}" for n in range(len(ids))) + "))"),
                       {f"i{n}": v for n, v in enumerate(ids)})
        db.execute(delete(LibPassage).where(LibPassage.authority_id.in_(ids)))
        db.execute(delete(LibAuthority).where(LibAuthority.id.in_(ids)))

    def remove(self, authority_id: str) -> None:
        with get_session() as db:
            self._delete_ids(db, [authority_id])
            db.commit()
        self._changed()

    def _changed(self) -> None:
        with self._lock:
            self.version += 1
            self._mem.clear()

    # ------------------------------------------------------------------ seed files
    def load_seed(self, source: str | Path, batch: int = 50) -> int:
        """Load a library file (path or URL) into the shared library. Re-running replaces by id."""
        src = str(source)
        log.info("loading library from %s", src)
        raw = urllib.request.urlopen(src, timeout=600) if re.match(r"https?://", src) else open(src, "rb")  # noqa: S310
        n, pending = 0, []
        with raw:
            header, items = read_seed(raw)
            if header.get("dims") and int(header["dims"]) != self.dims:
                raise ValueError(f"library vectors have {header['dims']} dimensions; EMBEDDING_DIMS is {self.dims}")
            self.last_header = header
            for j, vecs in items:
                pending.append((j, None, vecs))
                if len(pending) >= batch:
                    self.add_many(pending)
                    n += len(pending)
                    pending = []
                    if n % 500 == 0:
                        log.info("library: %d authorities loaded", n)
            if pending:
                self.add_many(pending)
                n += len(pending)
        log.info("library loaded: %d authorities", n)
        return n

    # ------------------------------------------------------------------ reading
    def authority(self, authority_id: str) -> Judgment | None:
        with get_session() as db:
            a = db.get(LibAuthority, authority_id)
            if a is None:
                return None
            rows = db.execute(select(LibPassage.pid, LibPassage.section, LibPassage.label, LibPassage.title,
                                     LibPassage.text).where(LibPassage.authority_id == authority_id)
                              .order_by(LibPassage.seq)).all()
        passages = tuple(Passage(authority_id, pid, section, body, label=label, title=title or "")
                         for pid, section, label, title, body in rows)
        return Judgment(a.id, a.name, a.citation, a.court, a.year, a.area, dict(a.doctrines or {}), passages,
                        kind=a.kind, url=a.url, date=a.date, summary=a.summary, source_note=a.source_note,
                        jurisdiction=a.jurisdiction)

    def _scope(self, firm_id: int | None, jurisdiction: str | None, alias: str = "a") -> tuple[str, dict]:
        sql = f"({alias}.firm_id IS NULL OR {alias}.firm_id = :firm)"
        params: dict = {"firm": firm_id if firm_id is not None else -1}
        if jurisdiction:
            sql += f" AND {alias}.jurisdiction = :jur"
            params["jur"] = jurisdiction
        return sql, params

    def keyword(self, query: str, firm_id, jurisdiction, kinds=None, only=None, limit=CANDIDATES) -> dict[int, float]:
        words = _query_words(query)
        if not words:
            return {}
        scope, params = self._scope(firm_id, jurisdiction)
        extra = ""
        if kinds:
            extra += " AND a.kind IN (" + ",".join(f":k{i}" for i in range(len(kinds))) + ")"
            params.update({f"k{i}": k for i, k in enumerate(kinds)})
        if only:
            extra += " AND p.authority_id = :only"
            params["only"] = only
        params["limit"] = limit
        with self.engine.connect() as c:
            if self.pg:
                params["q"] = " | ".join(words)
                rows = c.execute(text(
                    "SELECT p.id, ts_rank_cd(p.tsv, q, 32) AS s FROM lib_passages p "
                    "JOIN lib_authorities a ON a.id = p.authority_id, to_tsquery('english', :q) q "
                    f"WHERE p.tsv @@ q AND {scope}{extra} ORDER BY s DESC LIMIT :limit"), params).all()
                return {r[0]: float(r[1]) for r in rows}
            params["q"] = " OR ".join(f'"{w}"' for w in words)
            rows = c.execute(text(
                "SELECT f.rowid, -bm25(lib_passages_fts) AS s FROM lib_passages_fts f "
                "JOIN lib_passages p ON p.id = f.rowid JOIN lib_authorities a ON a.id = p.authority_id "
                f"WHERE lib_passages_fts MATCH :q AND {scope}{extra} ORDER BY bm25(lib_passages_fts) LIMIT :limit"),
                params).all()
            return {r[0]: max(float(r[1]), 0.0) for r in rows}

    def semantic(self, qv: np.ndarray, firm_id, jurisdiction, kinds=None, only=None,
                 limit=CANDIDATES) -> dict[int, float]:
        """Cosine similarity of the closest passages to the query vector."""
        if self.pg:
            if not self.vec_type:
                return {}
            scope, params = self._scope(firm_id, jurisdiction)
            extra = ""
            if kinds:
                extra += " AND a.kind IN (" + ",".join(f":k{i}" for i in range(len(kinds))) + ")"
                params.update({f"k{i}": k for i, k in enumerate(kinds)})
            # For one authority, order by an expression the HNSW index cannot serve, so every passage is scored.
            order = f"(p.vec <=> CAST(:qv AS {self.vec_type}))" + (" + 0" if only else "")
            if only:
                extra += " AND p.authority_id = :only"
                params["only"] = only
            params.update(qv=_vec_literal(qv), limit=limit)
            with self.engine.begin() as c:
                c.execute(text("SET LOCAL hnsw.ef_search = 200"))
                if self.pgvector >= (0, 8):  # keeps returning rows when filters remove index hits
                    c.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
                rows = c.execute(text(
                    f"SELECT p.id, 1 - (p.vec <=> CAST(:qv AS {self.vec_type})) FROM lib_passages p "
                    f"JOIN lib_authorities a ON a.id = p.authority_id "
                    f"WHERE p.vec IS NOT NULL AND {scope}{extra} ORDER BY {order} LIMIT :limit"), params).all()
            return {r[0]: float(r[1]) for r in rows}
        ids, mat = self._sqlite_vectors(firm_id, jurisdiction)
        if not len(ids):
            return {}
        sims = mat @ qv.astype(np.float32)
        if kinds or only:
            allowed = self._ids_where(firm_id, jurisdiction, kinds, only)
            sims = np.where(np.isin(ids, list(allowed)), sims, -2.0)
        top = np.argsort(-sims)[:limit]
        return {int(ids[i]): float(sims[i]) for i in top if sims[i] > -2.0}

    def _sqlite_vectors(self, firm_id, jurisdiction) -> tuple[np.ndarray, np.ndarray]:
        key = (firm_id, jurisdiction)
        with self._lock:
            if key in self._mem:
                return self._mem[key]
        scope, params = self._scope(firm_id, jurisdiction)
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT p.id, p.embedding FROM lib_passages p JOIN lib_authorities a "
                                  f"ON a.id = p.authority_id WHERE p.embedding IS NOT NULL AND {scope}"), params).all()
        ids = np.array([r[0] for r in rows], dtype=np.int64)
        mat = (np.stack([np.frombuffer(r[1], dtype=np.float16) for r in rows]).astype(np.float32)
               if rows else np.zeros((0, self.dims), dtype=np.float32))
        with self._lock:
            self._mem[key] = (ids, mat)
        return ids, mat

    def _ids_where(self, firm_id, jurisdiction, kinds, only) -> set[int]:
        scope, params = self._scope(firm_id, jurisdiction)
        extra = ""
        if kinds:
            extra += " AND a.kind IN (" + ",".join(f":k{i}" for i in range(len(kinds))) + ")"
            params.update({f"k{i}": k for i, k in enumerate(kinds)})
        if only:
            extra += " AND p.authority_id = :only"
            params["only"] = only
        with self.engine.connect() as c:
            return {r[0] for r in c.execute(text("SELECT p.id FROM lib_passages p JOIN lib_authorities a "
                                                 f"ON a.id = p.authority_id WHERE {scope}{extra}"), params)}

    def rescore(self, ids: list[int], query: str, qv: np.ndarray | None) -> dict[int, tuple[str, str, float, float]]:
        """For candidate passages: (authority id, pid, keyword score, cosine similarity)."""
        if not ids:
            return {}
        words = _query_words(query)
        out: dict[int, tuple[str, str, float, float]] = {}
        with self.engine.connect() as c:
            if self.pg:
                kw = "ts_rank_cd(p.tsv, to_tsquery('english', :q), 32)" if words else "0"
                sim = f"1 - (p.vec <=> CAST(:qv AS {self.vec_type}))" if (qv is not None and self.vec_type) else "0"
                params = {"ids": ids, "q": " | ".join(words)}
                if qv is not None and self.vec_type:
                    params["qv"] = _vec_literal(qv)
                for pid_, aid, pid, k, s in c.execute(text(
                        f"SELECT p.id, p.authority_id, p.pid, {kw}, coalesce({sim}, 0) FROM lib_passages p "
                        "WHERE p.id = ANY(:ids)"), params):
                    out[pid_] = (aid, pid, float(k or 0), float(s or 0))
                return out
            marks = ",".join(str(int(i)) for i in ids)
            kw: dict[int, float] = {}
            if words:
                q = " OR ".join(f'"{w}"' for w in words)
                kw = {r[0]: max(-float(r[1]), 0.0) for r in c.execute(text(
                    f"SELECT rowid, bm25(lib_passages_fts) FROM lib_passages_fts WHERE lib_passages_fts MATCH :q "
                    f"AND rowid IN ({marks})"), {"q": q})}
            for pid_, aid, pid, emb in c.execute(text(
                    f"SELECT id, authority_id, pid, embedding FROM lib_passages WHERE id IN ({marks})")):
                s = float(np.frombuffer(emb, dtype=np.float16).astype(np.float32) @ qv) if (emb and qv is not None) else 0.0
                out[pid_] = (aid, pid, kw.get(pid_, 0.0), s)
        return out


def _vec_literal(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.5f}" for x in np.asarray(v, dtype=np.float32)) + "]"


# ---------------------------------------------------------------------- corpus and retriever
class DBCorpus:
    """The Corpus interface over the database: authorities load on demand and are cached."""

    def __init__(self, store: LibraryStore, firm_id: int | None, jurisdiction: str | None, meta: dict | None = None,
                 max_cached: int = 400):
        self.store, self.firm_id, self.jurisdiction = store, firm_id, jurisdiction
        self.meta = meta or {}
        self._cache: OrderedDict[str, Judgment | None] = OrderedDict()
        self._max = max_cached
        self._len: int | None = None
        self._acts: dict[str, str] | None = None
        self._lock = threading.Lock()

    def _visible(self, a_firm, a_jur) -> bool:
        if a_firm is not None and a_firm != self.firm_id:
            return False
        if self.jurisdiction:
            from legal_brief.jurisdiction import same

            return same(a_jur, self.jurisdiction)
        return True

    def get(self, judgment_id: str) -> Judgment | None:
        with self._lock:
            if judgment_id in self._cache:
                self._cache.move_to_end(judgment_id)
                return self._cache[judgment_id]
        j = self.store.authority(judgment_id)
        if j is not None:
            with get_session() as db:
                firm = db.execute(select(LibAuthority.firm_id).where(LibAuthority.id == judgment_id)).scalar()
            if not self._visible(firm, j.jurisdiction):
                j = None
        with self._lock:
            self._cache[judgment_id] = j
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)
        return j

    def passage(self, ref: str) -> Passage | None:
        jid, _, pid = ref.partition(":")
        j = self.get(jid) if pid else None
        return j.passage(pid) if j else None

    def __contains__(self, judgment_id: str) -> bool:
        return self.get(judgment_id) is not None

    def __len__(self) -> int:
        if self._len is None:
            scope, params = self.store._scope(self.firm_id, self.jurisdiction)
            with self.store.engine.connect() as c:
                self._len = c.execute(text(f"SELECT count(*) FROM lib_authorities a WHERE {scope}"), params).scalar_one()
        return self._len

    @property
    def passages(self) -> list[Passage]:  # only for small diagnostics; never used on the full library
        return [p for j in self.judgments for p in j.passages]

    @property
    def judgments(self) -> list[Judgment]:
        scope, params = self.store._scope(self.firm_id, self.jurisdiction)
        with self.store.engine.connect() as c:
            ids = [r[0] for r in c.execute(text(f"SELECT id FROM lib_authorities a WHERE {scope} ORDER BY id"), params)]
        return [j for j in (self.get(i) for i in ids) if j]

    def for_jurisdiction(self, jurisdiction: str) -> "DBCorpus":
        from legal_brief.jurisdiction import normalise

        return DBCorpus(self.store, self.firm_id, normalise(jurisdiction), self.meta)

    def jurisdictions(self) -> dict[str, int]:
        scope, params = self.store._scope(self.firm_id, None)
        with self.store.engine.connect() as c:
            return {r[0]: r[1] for r in c.execute(text(
                f"SELECT a.jurisdiction, count(*) FROM lib_authorities a WHERE {scope} GROUP BY a.jurisdiction"), params)}

    def find_act(self, name: str) -> Judgment | None:
        if self._acts is None:
            scope, params = self.store._scope(self.firm_id, self.jurisdiction)
            with self.store.engine.connect() as c:
                self._acts = {_act_key(n): i for i, n in c.execute(text(
                    f"SELECT a.id, a.name FROM lib_authorities a WHERE a.kind = 'legislation' AND {scope}"), params)}
        aid = self._acts.get(_act_key(name))
        return self.get(aid) if aid else None

    def find_by_name(self, name: str) -> Judgment | None:
        """Match a free-text case name ('Anjanappa v Nanjundappa') to a judgment in the library."""
        key = _name_key(name)
        if not key:
            return None
        first, second, second_raw = key
        words = sorted(first or second or second_raw, key=len, reverse=True)[:2]
        if not words:
            return None
        scope, params = self.store._scope(self.firm_id, self.jurisdiction)
        cond = " AND ".join(f"a.name_key LIKE :w{i}" for i in range(len(words)))
        params.update({f"w{i}": f"%{w}%" for i, w in enumerate(words)})
        with self.store.engine.connect() as c:
            cands = c.execute(text(f"SELECT a.id, a.name FROM lib_authorities a WHERE a.kind <> 'legislation' "
                                   f"AND {cond} AND {scope} LIMIT 50"), params).all()
        for aid, cand in cands:
            jfirst, jsecond, jsecond_raw = _name_key(cand) or (set(), set(), set())
            first_ok = bool(first & jfirst) or not first
            second_ok = bool(second & jsecond) or (not second and second_raw and second_raw <= jsecond_raw)
            if first_ok and second_ok and (first or second):
                return self.get(aid)
        return None


class DBRetriever:
    """HybridRetriever's interface, answered by database queries."""

    def __init__(self, store: LibraryStore, corpus: DBCorpus, *, bm25_weight: float = 0.6,
                 doctrine_boost: float = 0.35):
        self.store, self.corpus = store, corpus
        self.bm25_weight = bm25_weight
        self.doctrine_boost = doctrine_boost
        self.embedder = store.embedder
        self.dense_mode = store.dense_mode

    def _qv(self, query: str) -> np.ndarray | None:
        if self.dense_mode != "embeddings":
            return None
        try:
            return self.embedder.embed_query(query)
        except Exception as e:  # noqa: BLE001 - one failed query falls back to keywords
            log.warning("query embedding failed: %s", e)
            return None

    def search_passages(self, query: str, top_k: int = 10, only: str | None = None,
                        kinds: tuple[str, ...] | None = None) -> list[PassageHit]:
        c = self.corpus
        qv = self._qv(query)
        cands = set(self.store.keyword(query, c.firm_id, c.jurisdiction, kinds, only))
        if qv is not None:
            cands |= set(self.store.semantic(qv, c.firm_id, c.jurisdiction, kinds, only))
        scored = self.store.rescore(sorted(cands), query, qv)
        if not scored:
            return []
        kw = np.array([v[2] for v in scored.values()])
        sims = np.array([v[3] for v in scored.values()])
        dn = np.clip(sims, 0.0, None)
        bm_n = kw / kw.max() if kw.max() > 0 else kw
        dn_n = dn / dn.max() if dn.max() > 0 else dn
        w = self.bm25_weight if qv is not None else 1.0
        fused = w * bm_n + (1 - w) * dn_n
        rows = list(scored.values())
        # The court's own paragraphs before the reporter's editorial headnote (pids h1, h2 ...).
        fused = fused * np.array([HEADNOTE_WEIGHT if re.fullmatch(r"h\d+", r[1]) else 1.0 for r in rows])
        order = np.argsort(-fused, kind="stable")[:top_k]
        return [PassageHit(f"{rows[i][0]}:{rows[i][1]}", rows[i][0], rows[i][1], float(fused[i]), float(bm_n[i]),
                           float(dn_n[i]), float(sims[i])) for i in order if fused[i] > 0]

    def best_passages(self, judgment_id: str, query: str, k: int = 3) -> list[str]:
        hits = self.search_passages(query, top_k=k, only=judgment_id)
        if hits:
            return [h.ref for h in hits]
        j = self.corpus.get(judgment_id)
        return [j.key_passage().ref] if j else []

    def search(self, query: str, top_k: int = 5, doctrine: str | None = None,
               doctrine_boost: float | None = None, kinds: tuple[str, ...] | None = None,
               prefer_area: str | None = None, area_boost: float = 0.2) -> list[JudgmentHit]:
        boost = self.doctrine_boost if doctrine_boost is None else doctrine_boost
        hits = self.search_passages(query, top_k=CANDIDATES, kinds=kinds)
        grouped: dict[str, list[PassageHit]] = defaultdict(list)
        for h in hits:
            grouped[h.judgment_id].append(h)
        meta = self._meta(list(grouped))
        results = []
        for jid, phits in grouped.items():
            area, doctrines = meta.get(jid, ("", {}))
            phits.sort(key=lambda h: -h.score)
            text_score = phits[0].score + 0.15 * sum(h.score for h in phits[1:3])
            tagged = bool(doctrine and doctrine in doctrines)
            in_area = bool(prefer_area and prefer_area in area.split(","))
            score = text_score + (boost if tagged else 0.0) + (area_boost if in_area else 0.0)
            results.append(JudgmentHit(jid, score, text_score, tagged, phits[:8]))
        results.sort(key=lambda r: (-r.score, r.judgment_id))
        return results[:top_k]

    def _meta(self, ids: list[str]) -> dict[str, tuple[str, dict]]:
        if not ids:
            return {}
        with get_session() as db:
            rows = db.execute(select(LibAuthority.id, LibAuthority.area, LibAuthority.doctrines)
                              .where(LibAuthority.id.in_(ids))).all()
        return {i: (a or "", d or {}) for i, a, d in rows}


__all__ = ["LibraryStore", "DBCorpus", "DBRetriever", "write_seed", "seed_to_authority", "doc_text", "SEED_FORMAT"]
