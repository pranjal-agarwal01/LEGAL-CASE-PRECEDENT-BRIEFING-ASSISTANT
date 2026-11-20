"""Precedent Retrieval Agent: runs RAG over the judgment corpus for every issue on
the shared issue list that has not been researched yet."""

from __future__ import annotations

import json

from pydantic import BaseModel

from legal_brief.agents.base import BaseLegalAgent
from legal_brief.memory import CandidatePrecedent, Issue


class _LLMSelection(BaseModel):
    issue_id: str
    judgment_ids: list[str]
    queries_used: list[str]
    reason: str
    coverage: str  # good | weak | none: does the library actually hold authority on this issue?
    coverage_note: str


class RetrievalSelectionLLM(BaseModel):
    selections: list[_LLMSelection]


class PrecedentRetrievalAgent(BaseLegalAgent):
    name = "precedent_retrieval"
    description = "Retrieves relevant judgments for each open issue (hybrid RAG)."
    tool_profile = "read"
    instructions = (
        "You are the Precedent Retrieval specialist in a legal briefing team ({jurisdiction}). For each issue you are given, find the "
        "judgments in the corpus that a careful lawyer would cite FOR or AGAINST the client. A hybrid search shortlist "
        "is provided; call search_judgments with your own reformulated queries (legal terms of art, doctrine names, "
        "analogous fact patterns) to find anything it missed, and read_passage when unsure. "
        "Prefer authorities from the matter's practice area, and leave out any from a different area of law that a "
        "specialist would not cite for this issue (for example a negligence case for a statutory employment claim, "
        "or the Sale of Goods Act 1979 for a consumer contract, which the Consumer Rights Act 2015 now governs). "
        "Return judgment_ids only from search results; never invent a case. Include authorities on both sides, and "
        "the statute that governs the issue when the library has one. Then judge coverage honestly: 'good' if the "
        "passages you found squarely address the issue, 'weak' if they are only analogous, 'none' if nothing in the "
        "library deals with this area of law (say what is missing in coverage_note). Never pad a weak shortlist."
    )

    def _hybrid(self, issue: Issue) -> list[CandidatePrecedent]:
        s = self.session
        query = s.issue_query(issue)
        hits = s.retriever.search(query, top_k=s.settings.top_k, doctrine=issue.doctrine,
                                  doctrine_boost=s.settings.doctrine_boost, prefer_area=s.fact_sheet.practice_area)
        # With few authorities (a firm's handful of statutes), look deeper inside each one.
        depth = 3 if len(s.corpus) > 12 else 6
        return [CandidatePrecedent(h.judgment_id, [p.ref for p in h.passages[:depth]], round(h.score, 4),
                                   "hybrid_rag", query=query[:160]) for h in hits]

    async def run(self) -> list[str]:
        pending = self.session.board.pending_retrieval()
        if not pending:
            return []
        self.session.log(self.name, "start", "issues: " + ", ".join(i.id for i in pending))
        shortlists = {i.id: self._hybrid(i) for i in pending}
        selected = await self.with_fallback("select", lambda: self._run_llm(pending, shortlists),
                                            lambda: shortlists)
        for issue in pending:
            self.session.board.attach_candidates(issue.id, selected.get(issue.id, shortlists[issue.id]), self.name)
            if not issue.candidates:
                self.session.board.set_coverage(issue.id, "none", "No authority in the library matched this issue.",
                                                 self.name)
            self.session.log(self.name, "attached", f"{issue.id}: {issue.candidate_ids()}")
        return [i.id for i in pending]

    async def _run_llm(self, pending: list[Issue], shortlists: dict[str, list[CandidatePrecedent]]):
        s = self.session
        payload = []
        for issue in pending:
            payload.append({
                "issue_id": issue.id, "question": issue.question, "doctrine": issue.doctrine,
                "hybrid_shortlist": [{"judgment_id": c.judgment_id, "kind": s.corpus.get(c.judgment_id).kind,
                                      "authority": s.corpus.get(c.judgment_id).full_name,
                                      "best_passages": [{"ref": r, "text": s.corpus.passage(r).text[:400]}
                                                        for r in c.passage_refs[:2] if s.corpus.passage(r)]}
                                     for c in shortlists[issue.id]],
            })
        prompt = (f"Case: {s.fact_sheet.title} (acting for the {s.fact_sheet.acting_for}; practice area: "
                  f"{s.fact_sheet.practice_area or 'not stated'}).\n\nFacts:\n"
                  + "\n".join(f"[{p.ref}] {p.text}" for p in s.fact_sheet.paragraphs)
                  + "\n\nIssues needing authorities:\n" + json.dumps(payload, indent=1)
                  + f"\n\nFor each issue select up to {s.settings.top_k + 2} judgments, most relevant first.")
        out = await self.ask(prompt, RetrievalSelectionLLM)
        result: dict[str, list[CandidatePrecedent]] = {}
        issue_by_id = {i.id: i for i in pending}
        for sel in out.selections:
            if sel.issue_id not in shortlists:
                continue
            base = {c.judgment_id: c for c in shortlists[sel.issue_id]}
            chosen: list[CandidatePrecedent] = []
            for jid in sel.judgment_ids:
                j = s.corpus.get(jid.strip())
                if not j or any(c.judgment_id == j.id for c in chosen):
                    continue  # unknown ids are discarded: retrieval only returns real judgments
                chosen.append(base.get(j.id) or CandidatePrecedent(
                    j.id, s.retriever.best_passages(j.id, s.issue_query(issue_by_id[sel.issue_id])),
                    0.0, "agent_search",
                    query="; ".join(sel.queries_used)[:160], reason=sel.reason))
            # Cap only the agent's own picks, then add every hybrid hit it did not mention, so the
            # agent can reorder and extend the shortlist but never lower recall below the baseline.
            chosen = chosen[: s.settings.top_k]
            s.board.set_coverage(sel.issue_id, (sel.coverage or "good").strip().lower(), sel.coverage_note.strip(),
                                 self.name)
            chosen += [c for c in shortlists[sel.issue_id] if c.judgment_id not in {x.judgment_id for x in chosen}]
            result[sel.issue_id] = chosen
        return result
