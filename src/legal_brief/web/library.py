"""The firm's library: the shared Indian library plus the firm's own uploads, searched in the database.

On startup the app makes sure the shared library is loaded. An empty database (a new Render free
database, for example) fills itself from the library file named by LIBRARY_SEED_URL, so nothing is lost
when the database is replaced: the law comes back from the file, and the firm's own work from a backup.
"""

from __future__ import annotations

import logging
import os
import threading

from sqlalchemy import select

from legal_brief.config import Settings
from legal_brief.corpus import Judgment, Passage
from legal_brief.embeddings import build_embedder
from legal_brief.jurisdiction import DEFAULT, normalise
from legal_brief.web.db import Authority, DBEmbeddingCache, LibAuthority, LibMeta, get_engine, get_session
from legal_brief.web.store import DBCorpus, DBRetriever, LibraryStore

log = logging.getLogger(__name__)


def upload_id(authority_id: int) -> str:
    return f"U{authority_id}"


def authority_to_judgment(a: Authority) -> Judgment:
    year = int(a.date[:4]) if a.date[:4].isdigit() else 0
    section = "provision" if a.kind == "legislation" else "paragraph"
    passages = tuple(Passage(upload_id(a.id), p.pid, section, p.text, label=p.label) for p in a.passages)
    return Judgment(upload_id(a.id), a.name or a.filename, a.citation, a.court or "", year, a.area,
                    dict(a.doctrines or {}), passages,
                    kind=a.kind if a.kind in ("judgment", "legislation") else "judgment",
                    url=a.url, date=a.date, summary=a.summary, source_note="Uploaded by you.",
                    jurisdiction=normalise(a.jurisdiction or DEFAULT))


class LibraryManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.embedder = build_embedder(settings, DBEmbeddingCache())
        self.store = LibraryStore(get_engine(), self.embedder, settings.embedding_dims)
        self.store.setup()
        self.seed_url = os.environ.get("LIBRARY_SEED_URL", "").strip()
        self.loading = False
        self._seed_lock = threading.Lock()

    @property
    def search_mode(self) -> str:
        return "semantic + keyword" if self.store.dense_mode == "embeddings" else "keyword"

    # ----------------------------------------------------------------- startup
    def warm(self) -> None:
        """Load the shared library if this database does not hold it yet, and index any upload that is
        missing from the search tables (an upload made before the search moved into the database)."""
        self.ensure_seeded()
        self.reindex_uploads()

    def seed_status(self) -> dict:
        with get_session() as db:
            row = db.get(LibMeta, "seed")
        return dict(row.value) if row else {}

    def ensure_seeded(self) -> None:
        if not self.seed_url:
            return
        with self._seed_lock:
            done = self.seed_status()
            if done.get("url") == self.seed_url and done.get("complete"):
                return
            self.loading = True
            try:
                n = self.store.load_seed(self.seed_url)
                with get_session() as db:
                    h = self.store.last_header
                    db.merge(LibMeta(key="seed", value={"url": self.seed_url, "complete": True, "authorities": n,
                                                        "source": h.get("source", ""), "built": h.get("built", "")}))
                    db.commit()
            except Exception as e:  # noqa: BLE001 - the app still serves uploads and accounts
                log.exception("could not load the library from %s: %s", self.seed_url, e)
            finally:
                self.loading = False

    def reindex_uploads(self) -> None:
        with get_session() as db:
            have = set(db.execute(select(LibAuthority.id).where(LibAuthority.firm_id.is_not(None))).scalars())
            ids = [i for i in db.execute(select(Authority.id).where(Authority.status == "ready")).scalars()
                   if upload_id(i) not in have]
        for i in ids:
            self.index_upload(i)

    # ----------------------------------------------------------------- uploads
    def index_upload(self, authority_id: int) -> None:
        with get_session() as db:
            a = db.get(Authority, authority_id)
            if a is None or a.status != "ready" or not a.passages:
                return
            j, firm_id = authority_to_judgment(a), a.firm_id
        self.store.add(j, firm_id=firm_id)

    def remove_upload(self, authority_id: int) -> None:
        self.store.remove(upload_id(authority_id))

    # ----------------------------------------------------------------- research
    def corpus(self, firm_id: int | None, jurisdiction: str | None = DEFAULT) -> DBCorpus:
        return DBCorpus(self.store, firm_id, normalise(jurisdiction) if jurisdiction else None,
                        meta=self.seed_status())

    def retriever(self, firm_id: int, include_summaries: bool = False, jurisdiction: str = DEFAULT) -> DBRetriever:
        """A retriever for one firm and jurisdiction. Cheap: the index lives in the database."""
        return DBRetriever(self.store, self.corpus(firm_id, jurisdiction),
                           doctrine_boost=self.settings.doctrine_boost)
