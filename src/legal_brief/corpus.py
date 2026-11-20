"""The authority library: case summaries, legislation and judgments a firm uploads.

Every authority has a short id and is split into citable passages:

    J06:p3     passage 3 of a leading-case teaching summary (data/corpus/judgments.json)
    L01:s62    section 62 of a statute (data/library/legislation.json)
    L01:sch2.1 part 1 of Schedule 2;  L30:reg13  regulation 13 of a statutory instrument
    U12:p45    paragraph 45 of judgment U12, uploaded by the firm

The class is still called `Judgment` for backwards compatibility; `Authority` is the
preferred name in new code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

COURT_WEIGHT = {
    "UK Supreme Court": 1.0,
    "House of Lords": 0.95,
    "Privy Council": 0.8,
    "Court of Appeal": 0.8,
    "High Court": 0.65,
    "Employment Appeal Tribunal": 0.65,
    "Upper Tribunal": 0.65,
}

KINDS = ("summary", "legislation", "judgment")
KIND_LABELS = {"summary": "Case summary", "legislation": "Legislation", "judgment": "Judgment"}


@dataclass(frozen=True)
class Passage:
    judgment_id: str
    pid: str
    section: str
    text: str
    label: str = ""  # display form: "¶45", "s 62", "Sch 2 (part 1 of 3)"
    title: str = ""  # heading of a statutory provision

    @property
    def ref(self) -> str:
        return f"{self.judgment_id}:{self.pid}"

    @property
    def display(self) -> str:
        if self.label:
            return self.label
        m = re.match(r"p(\d+)$", self.pid)
        return f"¶{m.group(1)}" if m else self.pid


@dataclass(frozen=True)
class Judgment:
    id: str
    name: str
    citation: str
    court: str
    year: int
    area: str
    doctrines: dict[str, str]
    passages: tuple[Passage, ...]
    kind: str = "summary"  # summary | legislation | judgment
    url: str = ""
    date: str = ""
    summary: str = ""
    source_note: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.name} {self.citation}".strip()

    @property
    def is_legislation(self) -> bool:
        return self.kind == "legislation"

    @property
    def court_weight(self) -> float:
        if self.is_legislation:
            return 1.0
        for court, w in COURT_WEIGHT.items():
            if court.lower() in self.court.lower():
                return w
        return 0.6

    def passage(self, pid: str) -> Passage | None:
        return next((p for p in self.passages if p.pid == pid), None)

    def section(self, name: str) -> Passage | None:
        return next((p for p in self.passages if p.section == name), None)

    def key_passage(self) -> Passage:
        """The passage that best states what the authority stands for."""
        return self.section("principle") or self.section("holding") or self.passages[-1 if self.kind == "summary" else 0]

    def cite(self, pid: str | None = None) -> str:
        """Human-readable citation, e.g. 'Consumer Rights Act 2015, s 62' or '*X v Y* [2020] UKSC 1, ¶12'."""
        p = self.passage(pid) if pid else None
        if self.is_legislation:
            return f"{self.name}, {p.display}" if p else self.name
        base = f"*{self.name}* {self.citation}".strip()
        return f"{base}, {p.display}" if p else base


Authority = Judgment


def first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return (m.group(1) if m else text).strip()


class Corpus:
    def __init__(self, judgments: list[Judgment], meta: dict | None = None):
        self.judgments = judgments
        self.meta = meta or {}
        self._by_id = {j.id: j for j in judgments}
        self.passages: list[Passage] = [p for j in judgments for p in j.passages]
        self._by_ref = {p.ref: p for p in self.passages}
        self._acts = {_act_key(j.name): j for j in judgments if j.is_legislation}

    # ------------------------------------------------------------ loading
    @classmethod
    def load(cls, path: Path) -> "Corpus":
        """Leading-case teaching summaries (the original 50-judgment corpus)."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        judgments = []
        for j in raw["judgments"]:
            # Teaching summaries are split into facts / holding / principle, not numbered judgment paragraphs,
            # so label them by section to avoid passing them off as paragraphs of the judgment.
            passages = tuple(Passage(j["id"], p["pid"], p["section"], p["text"], label=f"summary ({p['section']})")
                             for p in j["passages"])
            judgments.append(
                Judgment(j["id"], j["name"], j["citation"], j["court"], int(j["year"]), j["area"],
                         dict(j.get("doctrines", {})), passages, kind="summary",
                         source_note="Teaching summary, paraphrased; check the official law report.")
            )
        return cls(judgments, raw.get("_meta"))

    @classmethod
    def load_legislation(cls, path: Path) -> "Corpus":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        acts = []
        for a in raw["acts"]:
            passages = tuple(
                Passage(a["id"], p["pid"], "provision", _with_title(p.get("title", ""), p["text"]),
                        label=p["label"], title=p.get("title", ""))
                for p in a["provisions"]
            )
            if not passages:
                continue
            acts.append(Judgment(a["id"], a["title"], "", "Parliament", int(a.get("year") or 0),
                                 ",".join(a.get("areas", [])), dict(a.get("doctrines", {})), passages,
                                 kind="legislation", url=a.get("url", ""), date=a.get("valid_date") or "",
                                 source_note=raw.get("_meta", {}).get("licence", "")))
        return cls(acts, raw.get("_meta"))

    @classmethod
    def merge(cls, *parts: "Corpus") -> "Corpus":
        js, meta = [], {}
        for c in parts:
            js += c.judgments
            meta.update(c.meta)
        return cls(js, meta)

    # ------------------------------------------------------------- lookup
    def get(self, judgment_id: str) -> Judgment | None:
        return self._by_id.get(judgment_id)

    def passage(self, ref: str) -> Passage | None:
        return self._by_ref.get(ref)

    def __contains__(self, judgment_id: str) -> bool:
        return judgment_id in self._by_id

    def __len__(self) -> int:
        return len(self.judgments)

    def find_act(self, name: str) -> Judgment | None:
        return self._acts.get(_act_key(name))

    def find_by_name(self, name: str) -> Judgment | None:
        """Match a free-text case name (e.g. 'Caparo v Dickman') to a judgment."""
        key = _name_key(name)
        if not key:
            return None
        first, second, second_raw = key
        for j in self.judgments:
            if j.is_legislation:
                continue
            jfirst, jsecond, jsecond_raw = _name_key(j.name) or (set(), set(), set())
            first_ok = bool(first & jfirst) or not first
            # A short form such as "Robinson v Chief Constable" names only generic words of the
            # second party, so accept it when those words all appear in the full name.
            second_ok = bool(second & jsecond) or (not second and second_raw and second_raw <= jsecond_raw)
            if first_ok and second_ok and (first or second):
                return j
        return None


def _with_title(title: str, text: str) -> str:
    """Statute passages start with the provision heading, so retrieval and readers see it once."""
    if not title or text.lstrip().lower().startswith(title.lower()[:40]):
        return text
    return title + "\n" + text


def _act_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower().replace("the ", "")).strip()


_GENERIC = {"the", "of", "and", "ltd", "plc", "co", "in", "re", "on", "for", "council", "borough", "district",
            "urban", "area", "health", "authority", "board", "committee", "management", "hospital", "police",
            "chief", "constable", "great", "britain", "uk", "southern", "contractors", "bros", "sons", "a", "at",
            "limited", "llp", "trust", "nhs", "foundation", "secretary", "state", "r", "ors", "anor"}


_CONNECTORS = {"the", "of", "and", "a", "at", "in", "on", "for", "re"}


def _name_key(name: str) -> tuple[set[str], set[str], set[str]] | None:
    """(distinctive words of party 1, distinctive words of party 2, all words of party 2)."""
    parts = re.split(r"\s+v\.?\s+", name.strip(), maxsplit=1)
    if len(parts) != 2:
        return None
    raw = lambda s: set(re.findall(r"[a-z']+", s.lower().split("(")[0].replace("'s", ""))) - _CONNECTORS  # noqa: E731
    first_raw, second_raw = raw(parts[0]), raw(parts[1])
    first, second = first_raw - _GENERIC, second_raw - _GENERIC
    return (first, second, second_raw) if (second_raw or second) else None


@lru_cache(maxsize=4)
def load_corpus(path: str) -> Corpus:
    return Corpus.load(Path(path))


@lru_cache(maxsize=4)
def load_legislation(path: str) -> Corpus:
    p = Path(path)
    return Corpus.load_legislation(p) if p.exists() else Corpus([])


@dataclass(frozen=True)
class LibrarySpec:
    """Which parts of the shared library to include (uploads are added per firm)."""

    summaries: bool = True
    legislation: bool = True
    extra: tuple = field(default_factory=tuple)


def load_library(settings, spec: LibrarySpec | None = None) -> Corpus:
    spec = spec or LibrarySpec(summaries=settings.include_summaries, legislation=settings.include_legislation)
    parts = []
    if spec.legislation:
        parts.append(load_legislation(str(settings.legislation_path)))
    if spec.summaries:
        parts.append(load_corpus(str(settings.corpus_path)))
    return Corpus.merge(*parts, *spec.extra)
