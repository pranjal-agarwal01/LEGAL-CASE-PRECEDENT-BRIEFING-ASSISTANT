"""Which country's law governs a matter, and whether the library can research it.

Precedent must never answer a question about one legal system with another's law. Before any
research starts, `check_jurisdiction` reads the facts and decides which law governs. If that is
not the matter's jurisdiction, or the firm's library holds no authority for it, the run stops with
a clear explanation instead of producing a brief from the wrong law.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

log = logging.getLogger(__name__)

DEFAULT = "India"

# Canonical names, and the words people use for them.
_ALIASES: dict[str, tuple[str, ...]] = {
    "England and Wales": ("england and wales", "england & wales", "england", "wales", "english law", "e&w"),
    "Scotland": ("scotland", "scots law", "scottish"),
    "Northern Ireland": ("northern ireland",),
    "Ireland": ("ireland", "republic of ireland", "irish"),
    "India": ("india", "indian", "punjab", "haryana", "delhi", "maharashtra", "uttar pradesh", "karnataka",
              "tamil nadu", "west bengal", "gujarat", "rajasthan", "kerala", "telangana"),
    "Pakistan": ("pakistan",),
    "United States": ("united states", "usa", "u.s.", "us law", "new york", "california", "texas", "delaware"),
    "Canada": ("canada", "ontario", "british columbia", "quebec"),
    "Australia": ("australia", "new south wales", "victoria (australia)", "queensland"),
    "Singapore": ("singapore",),
    "Hong Kong": ("hong kong",),
    "UAE": ("uae", "united arab emirates", "dubai", "abu dhabi", "difc"),
    "Nigeria": ("nigeria",),
    "Kenya": ("kenya",),
    "South Africa": ("south africa",),
}

# Offline cues: words in a set of facts that point clearly to one legal system.
_CUES: dict[str, tuple[str, ...]] = {
    "India": (r"\brupees?\b|\brs\.?\s?\d|₹", r"\b(lakh|crore)s?\b", r"\b(kanals?|marlas?|bighas?|guntha|acres? of agricultural)\b",
              r"\b(tehsil(dar)?|patwari|kanungo|jamabandi|khasra|khatauni|girdawari|lambardar|sarpanch)\b",
              r"\b(ludhiana|amritsar|jalandhar|chandigarh|punjab|haryana|delhi|mumbai|pune|bengaluru|chennai|"
              r"kolkata|hyderabad|lucknow|jaipur)\b",
              r"\b(sale deed|mutation (entry|record)|demarcation report|record of rights|fard)\b",
              r"\b(high court of (punjab|delhi|bombay|madras|calcutta)|supreme court of india)\b"),
    "Scotland": (r"\bsheriff (court|principal)\b", r"\bcourt of session\b", r"\b(edinburgh|glasgow|aberdeen|dundee|inverness)\b",
                 r"\bscots law\b", r"\b(pursuer|defender)\b"),
    "United States": (r"\$\s?\d", r"\b(state|federal|district) court\b", r"\b(county|attorney general|u\.s\.c\.)\b",
                      r"\b(new york|california|texas|florida|illinois|delaware)\b"),
    "Ireland": (r"€\s?\d", r"\b(dublin|cork|galway|limerick)\b", r"\bcircuit court\b"),
    "Pakistan": (r"\b(lahore|karachi|islamabad|rawalpindi|peshawar)\b", r"\bpakistan\b"),
}


def normalise(name: str | None) -> str:
    """Canonical jurisdiction name ('England and Wales', 'India', ...); unknown names are title-cased."""
    n = (name or "").strip().lower().replace("’", "'")
    if not n:
        return DEFAULT
    for canon, aliases in _ALIASES.items():
        if n == canon.lower() or n in aliases:
            return canon
    for canon, aliases in _ALIASES.items():  # "law of India", "Indian law (Punjab)"
        if any(re.search(rf"\b{re.escape(a)}\b", n) for a in aliases if len(a) > 3):
            return canon
    return " ".join(w.capitalize() for w in n.split())


def same(a: str | None, b: str | None) -> bool:
    return normalise(a) == normalise(b)


def detect_offline(text: str) -> tuple[str | None, list[str]]:
    """(jurisdiction, matched cues) when at least two distinct cues point to one non-default system."""
    low = text.lower()
    best, best_hits = None, []
    for juris, patterns in _CUES.items():
        hits = [m.group(0) for p in patterns for m in [re.search(p, low)] if m]
        if len(hits) >= 2 and len(hits) > len(best_hits):
            best, best_hits = juris, hits
    return best, best_hits


class _GoverningLaw(BaseModel):
    governing_law: str  # e.g. "England and Wales", "India", "Scotland", "New York, United States"
    confidence: str  # high | medium | low
    reason: str


INSTRUCTIONS = (
    "You decide which legal system's law governs a dispute, for a law firm's research tool. Read the facts and "
    "answer with the jurisdiction whose courts and law would decide it: where the land is, where the parties and "
    "events are, the currency and land measures used, the courts and officials named, and any choice-of-law "
    "clause (which wins for a contract). Use names such as 'England and Wales', 'Scotland', 'India', 'Ireland', "
    "'New York, United States'. Never infer the jurisdiction from the parties' names, ethnicity, religion or "
    "nationality: people of every background live and litigate everywhere. Confidence is 'high' only when the "
    "facts make it plain. Keep the reason short and name the facts that decide it."
)


@dataclass
class JurisdictionCheck:
    matter: str
    detected: str | None = None
    confidence: str = "low"
    reason: str = ""
    cues: list[str] = field(default_factory=list)
    library_count: int = 0

    @property
    def mismatch(self) -> bool:
        return bool(self.detected) and not same(self.detected, self.matter) and self.confidence in ("high", "medium")

    def as_dict(self) -> dict:
        return {"matter_jurisdiction": normalise(self.matter), "detected": normalise(self.detected) if self.detected else None,
                "confidence": self.confidence, "reason": self.reason, "cues": self.cues[:6],
                "library_count": self.library_count}


class JurisdictionBlocked(RuntimeError):
    """The run must not proceed: the facts are governed by another jurisdiction's law, or the library has no
    authority for the matter's jurisdiction."""

    def __init__(self, kind: str, check: JurisdictionCheck, message: str):
        super().__init__(message)
        self.kind = kind  # mismatch | no_library
        self.check = check

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": str(self), **self.check.as_dict()}


async def check_jurisdiction(fact_sheet, corpus, client=None, override: bool = False) -> JurisdictionCheck:
    """Raise JurisdictionBlocked unless the matter can safely be researched with this library."""
    matter = normalise(fact_sheet.jurisdiction)
    chk = JurisdictionCheck(matter=matter, library_count=len(corpus))
    text = fact_sheet.raw_text or "\n".join(p.text for p in fact_sheet.paragraphs)
    off, cues = detect_offline(text)
    chk.cues = cues
    if client is not None:
        try:
            from agent_framework import Agent

            from legal_brief.llm import run_structured

            agent = Agent(client, INSTRUCTIONS, name="jurisdiction_check")
            out = await run_structured(agent, fact_sheet.numbered_text(), _GoverningLaw, max_tokens=400)
            chk.detected, chk.confidence, chk.reason = out.governing_law, out.confidence.lower().strip(), out.reason
        except Exception as e:  # noqa: BLE001 - fall back to the keyword cues
            log.warning("jurisdiction check by model failed: %s", e)
    if chk.detected is None and off:
        chk.detected, chk.confidence = off, "high" if len(cues) >= 3 else "medium"
        chk.reason = "The facts mention " + ", ".join(cues[:4]) + "."
    elif off and chk.detected and same(chk.detected, matter) and not same(off, matter) and len(cues) >= 3:
        # strong local cues outweigh a model that simply echoed the matter's jurisdiction
        chk.detected, chk.confidence = off, "medium"
        chk.reason = (chk.reason + " " if chk.reason else "") + "The facts also mention " + ", ".join(cues[:4]) + "."
    if not override and chk.mismatch:
        raise JurisdictionBlocked(
            "mismatch", chk,
            f"These facts appear to be governed by the law of {normalise(chk.detected)}, but the matter is set to "
            f"{matter}. Precedent will not research it with {matter} law. {chk.reason}".strip())
    if len(corpus) == 0:
        raise JurisdictionBlocked(
            "no_library", chk,
            f"Your library holds no legislation or judgments for {matter}. Upload the statutes and judgments you "
            f"rely on for {matter} before preparing a brief.")
    return chk
