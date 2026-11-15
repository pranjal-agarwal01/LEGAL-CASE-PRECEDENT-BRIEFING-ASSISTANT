"""Argument Agent: frames the legal issues and argues the client's (supporting) side
from the retrieved precedents."""

from __future__ import annotations

from legal_brief.agents.debate_base import CITATION_RULES, DebaterAgent, PrepareLLM
from legal_brief.doctrines import DOCTRINES, opposite


class ArgumentAgent(DebaterAgent):
    name = "argument"
    side = "argument"
    description = "Frames the legal issues and argues the client's side from retrieved precedents."
    instructions = (
        "You are the Argument Agent, an advocate for the client in a structured legal debate (England and Wales). "
        "First you frame the legal issues precisely; then, in each round, you argue the client's side using only "
        "the retrieved authorities and the numbered facts. Prefer binding, higher-court authority, explain why each "
        "authority applies to these facts, and answer the opponent's points directly. You may use search_judgments, "
        "read_passage and list_issues to check material. " + CITATION_RULES
    )

    # Issue framing: rewrite each candidate issue with the parties' names and fix the answer the client needs.
    def _prepare_offline(self) -> None:
        s, f = self.session, self.session.facts
        for issue in s.board.issues:
            d = DOCTRINES.get(issue.doctrine or "")
            if not d:
                continue
            position = d.claimant_wants if f.client_role == "claimant" else opposite(d.claimant_wants)
            s.board.frame_issue(issue.id, d.frame(f.claimant_label, f.defendant_label), position, self.name)
            for j in self.my_precedents(issue):
                s.board.mark_stance(issue.id, j.id, "supporting", self.name, "framing review")
        s.log(self.name, "framed", f"{len(s.board.issues)} issues")

    async def _prepare_llm(self) -> None:
        s = self.session
        prompt = (self.material() + "\n\nTASK: Frame the issues. For every issue on the shared list give a precise "
                  "question naming the parties and say whether the client needs the answer to be yes ('pro') or no "
                  "('contra'). If the facts raise an important issue that is missing, add it under new_issues with "
                  f"a doctrine key from: {', '.join(DOCTRINES)}. Do not duplicate existing issues.")
        out = await self.ask(prompt, PrepareLLM)
        for fi in out.framed_issues:
            if s.board.get(fi.issue_id):
                s.board.frame_issue(fi.issue_id, fi.question,
                                    "contra" if fi.client_needs.lower().startswith("contra") else "pro", self.name)
        for ni in out.new_issues:
            d = DOCTRINES.get(ni.doctrine)
            s.board.add_issue(ni.question, ni.doctrine if d else None, self.name,
                              d.claimant_wants if d else "pro", ni.reason)
        s.log(self.name, "framed", f"{len(out.framed_issues)} framed, {len(out.new_issues)} added")
