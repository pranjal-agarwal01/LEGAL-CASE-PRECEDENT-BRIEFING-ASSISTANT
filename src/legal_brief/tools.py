"""Agent Framework function tools that give LLM agents access to RAG and shared memory.

Tools are built per agent so writes to the issue board are attributed to the
agent that made them.
"""

from __future__ import annotations

import json
from typing import Annotated

from agent_framework import FunctionTool, tool

from legal_brief.corpus import Corpus
from legal_brief.doctrines import DOCTRINES
from legal_brief.memory import CandidatePrecedent, IssueBoard
from legal_brief.retrieval import HybridRetriever


def make_tools(agent_name: str, *, corpus: Corpus, retriever: HybridRetriever, board: IssueBoard,
               top_k: int = 5, can_write: bool = True) -> list[FunctionTool]:

    def search_judgments(
        query: Annotated[str, "Natural-language search over the authority library"],
        doctrine: Annotated[str, "Optional doctrine key to prioritise, e.g. 'frustration' or ''"] = "",
    ) -> str:
        hits = retriever.search(query, top_k=top_k, doctrine=doctrine or None)
        out = []
        for h in hits:
            j = corpus.get(h.judgment_id)
            out.append({
                "judgment_id": h.judgment_id, "kind": j.kind, "authority": j.full_name,
                "court": "" if j.is_legislation else j.court, "score": round(h.score, 3),
                "passages": [{"ref": p.ref, "label": corpus.passage(p.ref).display, "text": corpus.passage(p.ref).text}
                             for p in h.passages[:2]],
            })
        return json.dumps(out)

    def read_passage(ref: Annotated[str, "Passage id such as 'J01:p2'"]) -> str:
        p = corpus.passage(ref.strip())
        if not p:
            return json.dumps({"error": f"{ref} does not exist in the corpus"})
        j = corpus.get(p.judgment_id)
        return json.dumps({"ref": p.ref, "authority": j.full_name, "kind": j.kind, "label": p.display,
                           "text": p.text})

    def list_issues() -> str:
        return board.compact_view(corpus)

    def add_issue(
        question: Annotated[str, "The legal question, phrased as a yes/no question"],
        doctrine: Annotated[str, f"One of: {', '.join(DOCTRINES)}"],
        reason: Annotated[str, "Why the facts raise this issue"] = "",
    ) -> str:
        d = doctrine if doctrine in DOCTRINES else None
        position = DOCTRINES[d].claimant_wants if d else "pro"
        issue = board.add_issue(question, d, agent_name, position, reason)
        return json.dumps({"issue_id": issue.id, "note": "Retrieval will run for new issues before the debate continues."})

    def record_precedent(
        issue_id: Annotated[str, "Issue id such as 'I1'"],
        judgment_id: Annotated[str, "Judgment id such as 'J01'"],
        stance: Annotated[str, "'supporting' or 'opposing' relative to the client"],
        reason: Annotated[str, "One sentence on why"] = "",
    ) -> str:
        if not corpus.get(judgment_id):
            return json.dumps({"error": f"{judgment_id} is not in the corpus; cite only retrieved judgments"})
        issue = board.get(issue_id)
        if not issue:
            return json.dumps({"error": f"no issue {issue_id}"})
        if judgment_id not in issue.candidate_ids():
            refs = retriever.best_passages(judgment_id, f"{issue.question} {reason}")
            board.attach_candidates(issue_id, [CandidatePrecedent(judgment_id, refs, 0.0, agent_name, reason=reason)],
                                    agent_name)
        board.mark_stance(issue_id, judgment_id, "supporting" if stance.startswith("support") else "opposing", agent_name, reason)
        return json.dumps({"ok": True})

    read_tools = [
        tool(search_judgments, name="search_judgments",
             description="Search the authority library (statutes, judgments and case summaries). Returns "
                         "authority ids, names and passage refs you may cite."),
        tool(read_passage, name="read_passage", description="Read the full text of one passage by its ref, e.g. 'J06:p3'."),
        tool(list_issues, name="list_issues", description="Read the shared issue list, including candidate precedents and stances so far."),
    ]
    write_tools = [
        tool(add_issue, name="add_issue", description="Add a new legal issue to the shared issue list."),
        tool(record_precedent, name="record_precedent",
             description="Record on the shared issue list that a judgment supports or opposes the client on an issue."),
    ]
    return read_tools + (write_tools if can_write else [])
