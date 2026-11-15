"""The judgment corpus: loading, lookup and short display helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

COURT_WEIGHT = {
    "UK Supreme Court": 1.0,
    "House of Lords": 0.95,
    "Privy Council": 0.8,
    "Court of Appeal": 0.8,
}


@dataclass(frozen=True)
class Passage:
    judgment_id: str
    pid: str
    section: str
    text: str

    @property
    def ref(self) -> str:
        return f"{self.judgment_id}:{self.pid}"


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

    @property
    def full_name(self) -> str:
        return f"{self.name} {self.citation}"

    @property
    def court_weight(self) -> float:
        return COURT_WEIGHT.get(self.court, 0.6)

    def passage(self, pid: str) -> Passage | None:
        return next((p for p in self.passages if p.pid == pid), None)

    def section(self, name: str) -> Passage | None:
        return next((p for p in self.passages if p.section == name), None)


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

    @classmethod
    def load(cls, path: Path) -> "Corpus":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        judgments = []
        for j in raw["judgments"]:
            passages = tuple(Passage(j["id"], p["pid"], p["section"], p["text"]) for p in j["passages"])
            judgments.append(
                Judgment(j["id"], j["name"], j["citation"], j["court"], int(j["year"]), j["area"],
                         dict(j.get("doctrines", {})), passages)
            )
        return cls(judgments, raw.get("_meta"))

    def get(self, judgment_id: str) -> Judgment | None:
        return self._by_id.get(judgment_id)

    def passage(self, ref: str) -> Passage | None:
        return self._by_ref.get(ref)

    def __contains__(self, judgment_id: str) -> bool:
        return judgment_id in self._by_id

    def __len__(self) -> int:
        return len(self.judgments)

    def find_by_name(self, name: str) -> Judgment | None:
        """Match a free-text case name (e.g. 'Caparo v Dickman') to a judgment."""
        key = _name_key(name)
        if not key:
            return None
        first, second, second_raw = key
        for j in self.judgments:
            jfirst, jsecond, jsecond_raw = _name_key(j.name) or (set(), set(), set())
            first_ok = bool(first & jfirst) or not first
            # A short form such as "Robinson v Chief Constable" names only generic words of the
            # second party, so accept it when those words all appear in the full name.
            second_ok = bool(second & jsecond) or (not second and second_raw and second_raw <= jsecond_raw)
            if first_ok and second_ok and (first or second):
                return j
        return None


_GENERIC = {"the", "of", "and", "ltd", "plc", "co", "in", "re", "on", "for", "council", "borough", "district",
            "urban", "area", "health", "authority", "board", "committee", "management", "hospital", "police",
            "chief", "constable", "great", "britain", "uk", "southern", "contractors", "bros", "sons", "a", "at"}


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
