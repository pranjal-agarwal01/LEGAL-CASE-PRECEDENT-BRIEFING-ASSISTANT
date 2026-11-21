"""The library file: a gzip JSON-lines export of authorities, their passages and (optionally) vectors.

Line 1 is a header {"format": "precedent-library/1", "dims": 512, ...}; every other line is one
authority with its passages. Vectors are float16, base64-encoded, one per passage.

scripts/india/build_library.py writes it; the web app loads it into an empty database
(LIBRARY_SEED_URL); the command line and the tests read it straight into memory.
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from typing import Iterator

import numpy as np

from legal_brief.corpus import Judgment, Passage

SEED_FORMAT = "precedent-library/1"


def authority_to_seed(j: Judgment, vectors: np.ndarray | None) -> dict:
    return {
        "id": j.id, "kind": j.kind, "name": j.name, "citation": j.citation, "court": j.court, "year": j.year,
        "date": j.date, "area": j.area, "jurisdiction": j.jurisdiction, "doctrines": j.doctrines, "url": j.url,
        "summary": j.summary, "source_note": j.source_note,
        "passages": [{"pid": p.pid, "section": p.section, "label": p.label, "title": p.title, "text": p.text,
                      "vec": None if vectors is None else
                      base64.b64encode(np.asarray(vectors[i], dtype=np.float16).tobytes()).decode("ascii")}
                     for i, p in enumerate(j.passages)],
    }


def seed_to_authority(d: dict) -> tuple[Judgment, np.ndarray | None]:
    passages = tuple(Passage(d["id"], p["pid"], p.get("section", "paragraph"), p["text"], label=p.get("label", ""),
                             title=p.get("title", "")) for p in d["passages"])
    j = Judgment(d["id"], d["name"], d.get("citation", ""), d.get("court", ""), int(d.get("year") or 0),
                 d.get("area", ""), dict(d.get("doctrines") or {}), passages, kind=d.get("kind", "judgment"),
                 url=d.get("url", ""), date=d.get("date", ""), summary=d.get("summary", ""),
                 source_note=d.get("source_note", ""), jurisdiction=d.get("jurisdiction", "India"))
    vecs = None
    if d["passages"] and all(p.get("vec") for p in d["passages"]):
        vecs = np.stack([np.frombuffer(base64.b64decode(p["vec"]), dtype=np.float16) for p in d["passages"]])
    return j, vecs


def write_seed(path: Path, items, dims: int, meta: dict | None = None) -> int:
    """Write (Judgment, vectors) pairs as a library file."""
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"format": SEED_FORMAT, "dims": dims, **(meta or {})}) + "\n")
        for j, vecs in items:
            f.write(json.dumps(authority_to_seed(j, vecs), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_seed(stream) -> tuple[dict, Iterator[tuple[Judgment, np.ndarray | None]]]:
    """(header, iterator of (authority, vectors)) from a binary stream of a library file."""
    f = gzip.open(stream, "rt", encoding="utf-8")
    header = json.loads(f.readline())
    if header.get("format") != SEED_FORMAT:
        raise ValueError(f"not a Precedent library file: {header.get('format')}")

    def items():
        with f:
            for line in f:
                if line.strip():
                    yield seed_to_authority(json.loads(line))

    return header, items()


def load_file(path: Path | str):
    """The whole library file as an in-memory Corpus (for the command line and tests)."""
    from legal_brief.corpus import Corpus

    with open(path, "rb") as raw:
        header, items = read_seed(raw)
        judgments = [j for j, _ in items]
    return Corpus(judgments, {k: v for k, v in header.items() if k not in ("format",)})
