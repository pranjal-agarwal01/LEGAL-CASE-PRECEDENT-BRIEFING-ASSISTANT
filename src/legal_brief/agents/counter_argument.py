"""Counter-Argument Agent: argues the opposing side from the retrieved precedents and
raises the defences the other side is likely to run."""

from __future__ import annotations

from legal_brief.agents.debate_base import CITATION_RULES, DebaterAgent, PrepareLLM
from legal_brief.doctrines import DOCTRINES, opposite, score_doctrines


class CounterArgumentAgent(DebaterAgent):
    name = "counter_argument"
    side = "counter"
    description = "Argues the opposing side from retrieved precedents and raises defences."
    instructions = (
        "You are the Counter-Argument Agent: opposing counsel in a structured legal debate ({jurisdiction}). "
        "Argue the strongest case AGAINST the client using only the retrieved authorities and the numbered facts: "
        "rely on restrictive or contrary precedent, distinguish the client's authorities on their facts, and press "
        "every evidential weakness in the facts. You may use search_judgments, read_passage and list_issues. "
        + CITATION_RULES
    )

    # Before the first round, the opposing side adds defence issues the facts support.
    def _prepare_offline(self) -> None:
        s, f = self.session, self.session.facts
        areas = {DOCTRINES[i.doctrine].area for i in s.board.issues if i.doctrine in DOCTRINES}
        for key, score in sorted(score_doctrines(s.fact_sheet.raw_text).items(), key=lambda kv: -kv[1]):
            d = DOCTRINES[key]
            if d.defence and score >= 2 and d.area in areas and not s.board.by_doctrine(key):
                position = d.claimant_wants if f.client_role == "claimant" else opposite(d.claimant_wants)
                s.board.add_issue(d.frame(f.claimant_label, f.defendant_label), key, self.name, position,
                                  f"defence raised by the opposing side ({score} cues)")

    async def _prepare_llm(self) -> None:
        s = self.session
        prompt = (self.material() + "\n\nTASK: Before the debate starts, list any DEFENCE issues the other side will "
                  "run that are missing from the shared issue list (e.g. causation, remoteness, an exclusion clause, "
                  f"no intention to be bound). Use doctrine keys from: {', '.join(DOCTRINES)}. Return framed_issues "
                  "as an empty list. Return new_issues as an empty list if nothing important is missing.")
        out = await self.ask(prompt, PrepareLLM)
        for ni in out.new_issues:
            d = DOCTRINES.get(ni.doctrine)
            s.board.add_issue(ni.question, ni.doctrine if d else None, self.name,
                              d.claimant_wants if d else "pro", ni.reason)
        s.log(self.name, "defences", f"{len(out.new_issues)} defence issue(s) proposed")
