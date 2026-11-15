"""Shared session state and the base class for the five specialised agents."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

from agent_framework import Agent
from pydantic import BaseModel

from legal_brief.config import Settings
from legal_brief.corpus import Corpus
from legal_brief.doctrines import DOCTRINES
from legal_brief.llm import run_structured
from legal_brief.memory import IssueBoard
from legal_brief.models import DebateTurn, FactSheet, StructuredFacts
from legal_brief.retrieval import HybridRetriever
from legal_brief.retrieval.index import tokenize
from legal_brief.tools import make_tools

log = logging.getLogger(__name__)
T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)

DEFENDANT_CUES = ("says", "argues", "relies", "denies", "refuses", "suggests", "claims the", "replied")


@dataclass
class CaseSession:
    """Everything one run shares: corpus, retriever, the issue board and the trace."""

    settings: Settings
    corpus: Corpus
    retriever: HybridRetriever
    fact_sheet: FactSheet
    client: Any | None = None  # Agent Framework chat client, None in offline mode
    board: IssueBoard = field(default_factory=IssueBoard)
    facts: StructuredFacts | None = None
    turns: list[DebateTurn] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    llm_calls: int = 0
    started: float = field(default_factory=time.perf_counter)

    @property
    def mode(self) -> str:
        return "llm:" + self.settings.provider if self.client is not None else "offline"

    def log(self, agent: str, action: str, detail: str = "") -> None:
        self.trace.append({"t": round(time.perf_counter() - self.started, 3), "agent": agent,
                           "action": action, "detail": detail, "round": self.board.round})
        log.info("[%s] %s %s", agent, action, detail)

    def turns_by(self, speaker: str) -> list[DebateTurn]:
        return [t for t in self.turns if t.speaker == speaker]

    # -------- helpers used by several agents ---------------------------------
    def best_fact(self, query: str, prefer_defendant: bool = False, exclude: set[str] | None = None,
                  doctrine: str | None = None) -> str | None:
        """Fact paragraph ref that best overlaps `query` (token overlap, doctrine cues, side-aware)."""
        import re

        q = set(tokenize(query))
        patterns = DOCTRINES[doctrine].patterns if doctrine in DOCTRINES else ()
        best, best_score = None, -1.0
        for p in self.fact_sheet.paragraphs:
            if p.kind != "fact" or (exclude and p.ref in exclude):
                continue
            toks = set(tokenize(p.text))
            score = len(q & toks) / (1 + len(toks) ** 0.5)
            score += 0.5 * sum(bool(re.search(pt, p.text.lower())) for pt in patterns)
            is_def = any(c in p.text.lower() for c in DEFENDANT_CUES)
            score += 0.6 if is_def == prefer_defendant else 0.0
            if score > best_score:
                best, best_score = p.ref, score
        return best

    def fact_text(self, ref: str, max_words: int = 40) -> str:
        p = self.fact_sheet.paragraph(ref)
        if not p:
            return ""
        words = p.text.split()
        return " ".join(words[:max_words]).rstrip(".,;") + ("..." if len(words) > max_words else ".")

    def issue_query(self, issue) -> str:
        d = DOCTRINES.get(issue.doctrine or "")
        query = f"{issue.question} {d.query_terms if d else ''}"
        ref = self.best_fact(query)
        return f"{query} {self.fact_sheet.paragraph(ref).text if ref else ''}"


class BaseLegalAgent:
    """One specialised agent. With an LLM configured it wraps an Agent Framework `Agent`;
    otherwise it runs a deterministic baseline so the pipeline works offline."""

    name: str = "agent"
    description: str = ""
    instructions: str = ""
    tool_profile: str = "none"  # none | read | write

    def __init__(self, session: CaseSession):
        self.session = session
        self.agent: Agent | None = None
        if session.client is not None:
            tools = []
            if self.tool_profile != "none":
                tools = make_tools(self.name, corpus=session.corpus, retriever=session.retriever,
                                   board=session.board, top_k=session.settings.top_k,
                                   can_write=self.tool_profile == "write")
            self.agent = Agent(session.client, self.instructions, name=self.name,
                               description=self.description, tools=tools or None)

    @property
    def uses_llm(self) -> bool:
        return self.agent is not None

    async def ask(self, prompt: str, schema: type[M]) -> M:
        assert self.agent is not None
        self.session.llm_calls += 1
        return await run_structured(self.agent, prompt, schema, max_tokens=self.session.settings.max_tokens)

    async def with_fallback(self, label: str, llm_step: Callable[[], Awaitable[T]], offline_step: Callable[[], T]) -> T:
        if not self.uses_llm:
            return offline_step()
        try:
            return await llm_step()
        except Exception as e:  # noqa: BLE001 - any provider/parse failure falls back to the baseline
            if self.session.settings.strict_llm:
                raise
            msg = f"{self.name}: LLM step '{label}' failed ({type(e).__name__}: {e}); used the offline baseline instead."
            self.session.warnings.append(msg)
            self.session.log(self.name, "llm_fallback", msg)
            return offline_step()
