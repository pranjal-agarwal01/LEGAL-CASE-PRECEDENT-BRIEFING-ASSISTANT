"""The shared issue list: the blackboard every agent reads from and writes to.

* Fact Extractor writes candidate issues found in the facts.
* Precedent Retrieval reads open issues and attaches candidate precedents.
* Argument Agent frames each issue and marks supporting precedents.
* Counter-Argument Agent adds defence issues and marks opposing precedents.
* Brief Compiler reads everything and records the final assessment.

Every write is appended to an event log, so the debate can be audited.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CandidatePrecedent:
    judgment_id: str
    passage_refs: list[str]
    score: float
    retrieved_by: str
    query: str = ""
    reason: str = ""


@dataclass
class Note:
    author: str
    round: int
    text: str


@dataclass
class Issue:
    id: str
    question: str
    doctrine: str | None
    raised_by: str
    client_position: str = "pro"  # answer the client needs: 'pro' (yes) or 'contra' (no)
    status: str = "open"  # open -> researched -> framed -> debated -> resolved
    retrieval_done: bool = False
    candidates: list[CandidatePrecedent] = field(default_factory=list)
    supporting: list[str] = field(default_factory=list)  # judgment ids
    opposing: list[str] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    assessment: str = ""
    coverage: str = "good"  # good | weak | none: does the library hold authority on this issue?
    coverage_note: str = ""

    def candidate_ids(self) -> list[str]:
        return [c.judgment_id for c in self.candidates]

    def candidate(self, judgment_id: str) -> CandidatePrecedent | None:
        return next((c for c in self.candidates if c.judgment_id == judgment_id), None)


@dataclass
class BoardEvent:
    seq: int
    author: str
    action: str
    issue_id: str | None
    detail: str


class IssueBoard:
    def __init__(self) -> None:
        self.issues: list[Issue] = []
        self.events: list[BoardEvent] = []
        self.round = 0

    # ----------------------------------------------------------- logging
    def _log(self, author: str, action: str, issue_id: str | None, detail: str) -> None:
        self.events.append(BoardEvent(len(self.events) + 1, author, action, issue_id, detail))

    # ------------------------------------------------------------- reads
    def get(self, issue_id: str) -> Issue | None:
        return next((i for i in self.issues if i.id == issue_id), None)

    def by_doctrine(self, doctrine: str) -> Issue | None:
        return next((i for i in self.issues if i.doctrine == doctrine), None)

    def pending_retrieval(self) -> list[Issue]:
        return [i for i in self.issues if not i.retrieval_done]

    def all_candidate_ids(self) -> list[str]:
        seen: list[str] = []
        for i in self.issues:
            for jid in i.candidate_ids():
                if jid not in seen:
                    seen.append(jid)
        return seen

    # ------------------------------------------------------------ writes
    def add_issue(self, question: str, doctrine: str | None, author: str,
                  client_position: str = "pro", reason: str = "") -> Issue:
        if doctrine:
            existing = self.by_doctrine(doctrine)
            if existing:
                self._log(author, "duplicate_issue_ignored", existing.id, question)
                return existing
        issue = Issue(id=f"I{len(self.issues) + 1}", question=question.strip(), doctrine=doctrine,
                      raised_by=author, client_position=client_position)
        self.issues.append(issue)
        self._log(author, "add_issue", issue.id, f"{question} [{doctrine or 'untyped'}] {reason}".strip())
        return issue

    def frame_issue(self, issue_id: str, question: str, client_position: str, author: str) -> None:
        issue = self.get(issue_id)
        if not issue:
            return
        issue.question, issue.client_position, issue.status = question.strip(), client_position, "framed"
        self._log(author, "frame_issue", issue_id, f"{question} (client needs: {client_position})")

    def attach_candidates(self, issue_id: str, candidates: list[CandidatePrecedent], author: str) -> None:
        issue = self.get(issue_id)
        if not issue:
            return
        for c in candidates:
            if c.judgment_id not in issue.candidate_ids():
                issue.candidates.append(c)
        issue.retrieval_done = True
        if issue.status == "open":
            issue.status = "researched"
        self._log(author, "attach_precedents", issue_id, ", ".join(c.judgment_id for c in candidates) or "none found")

    def set_coverage(self, issue_id: str, coverage: str, note: str, author: str) -> None:
        issue = self.get(issue_id)
        if not issue or coverage not in ("good", "weak", "none"):
            return
        issue.coverage, issue.coverage_note = coverage, note
        self._log(author, "coverage", issue_id, f"{coverage}: {note}"[:200])

    def mark_stance(self, issue_id: str, judgment_id: str, stance: str, author: str, reason: str = "") -> None:
        issue = self.get(issue_id)
        if not issue:
            return
        target = issue.supporting if stance == "supporting" else issue.opposing
        if judgment_id not in target:
            target.append(judgment_id)
            self._log(author, f"mark_{stance}", issue_id, f"{judgment_id} {reason}".strip())

    def add_note(self, issue_id: str, text: str, author: str) -> None:
        issue = self.get(issue_id)
        if issue:
            issue.notes.append(Note(author, self.round, text))
            if issue.status in ("researched", "framed"):
                issue.status = "debated"
            self._log(author, "note", issue_id, text[:160])

    def resolve(self, issue_id: str, assessment: str, author: str) -> None:
        issue = self.get(issue_id)
        if issue:
            issue.assessment, issue.status = assessment, "resolved"
            self._log(author, "resolve", issue_id, assessment[:160])

    # ------------------------------------------------------- serialising
    def snapshot(self) -> dict[str, Any]:
        return {"round": self.round, "issues": [asdict(i) for i in self.issues]}

    def to_json(self, with_events: bool = True) -> str:
        data = self.snapshot()
        if with_events:
            data["events"] = [asdict(e) for e in self.events]
        return json.dumps(data, indent=2)

    def compact_view(self, corpus=None) -> str:
        """A short JSON view of the board that fits comfortably in an LLM prompt."""
        rows = []
        for i in self.issues:
            rows.append({
                "issue_id": i.id, "question": i.question, "doctrine": i.doctrine, "raised_by": i.raised_by,
                "client_needs_answer": i.client_position, "status": i.status,
                "candidates": [
                    {"judgment_id": c.judgment_id,
                     "case": corpus.get(c.judgment_id).full_name if corpus and corpus.get(c.judgment_id) else "",
                     "passages": c.passage_refs}
                    for c in i.candidates
                ],
                "supporting": i.supporting, "opposing": i.opposing,
                "notes": [f"{n.author}: {n.text}" for n in i.notes[-4:]],
            })
        return json.dumps(rows, indent=1)
