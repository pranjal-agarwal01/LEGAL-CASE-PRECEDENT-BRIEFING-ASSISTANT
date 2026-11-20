"""Brief Compiler: merges both sides of the debate into a short brief in which every
claim carries a citation, then runs the citation guard."""

from __future__ import annotations

from pydantic import BaseModel

from legal_brief.agents.base import BaseLegalAgent
from legal_brief.citations import CitationReport, CitationValidator, audit_brief, guard_brief
from legal_brief.corpus import first_sentence
from legal_brief.memory import Issue
from legal_brief.models import Brief, CitedStatement, IssueAnalysis, PrecedentEntry
from legal_brief.verification import verify_brief


# ----------------------------------------------------------------- LLM schema
class _LLMStatement(BaseModel):
    text: str
    citations: list[str]


class _LLMPrecedent(BaseModel):
    judgment_id: str
    stance: str  # supporting | opposing (relative to the client)
    proposition: str
    citations: list[str]
    quote: str  # the exact words of the cited passage the proposition rests on, copied verbatim


class _LLMIssueSection(BaseModel):
    issue_id: str
    question: str
    precedents: list[_LLMPrecedent]
    supporting_argument: list[_LLMStatement]
    opposing_argument: list[_LLMStatement]
    assessment: _LLMStatement


class BriefLLM(BaseModel):
    summary: list[_LLMStatement]
    issues: list[_LLMIssueSection]
    conclusion: list[_LLMStatement]
    remedies: list[_LLMStatement]
    time_limits: list[_LLMStatement]
    evidence: list[_LLMStatement]
    questions_for_client: list[str]


class CompiledBrief(BaseModel):
    raw: Brief
    final: Brief
    raw_report: dict
    final_report: dict
    support_report: dict = {}


class BriefCompilerAgent(BaseLegalAgent):
    name = "brief_compiler"
    description = "Merges the argument and counter-argument into a short, fully cited brief."
    tool_profile = "read"
    instructions = (
        "You are the Brief Compiler. You receive a structured debate between the client's advocate and opposing "
        "counsel, the shared issue list and the retrieved authorities. Write a short, balanced brief for a "
        "supervising lawyer: a summary, then for each issue the supporting and opposing precedents with the "
        "proposition each stands for, the best points on each side, and a reasoned assessment. Every statement must "
        "cite at least one passage id (e.g. 'J06:p3', 'L21:s11.1', 'U4:p37') or fact ref (e.g. 'F2') from the "
        "material provided, and each cited passage must itself support the statement; issue ids "
        "such as 'I1' are labels, never citations. Never introduce an authority that is not in the material. For "
        "each issue, list every authority either debater relied on or attacked, on the correct side, and give "
        "its 'quote': 8-40 words copied EXACTLY from the cited passage (no paraphrase, no ellipsis inside). Be "
        "concise: one to three sentences per statement.\n"
        "Then write the practical next steps a supervising solicitor needs:\n"
        "- remedies: what the client can claim or the court or tribunal can order, including statutory sanctions, "
        "each citing the passage id of the provision that CREATES that remedy (for example the section giving the "
        "right to complain or setting the award), not a section that only defines the right.\n"
        "- time_limits: every deadline that matters (limitation, tribunal time limits, statutory notice periods), "
        "citing the provision by its passage id (never by a description). Take every period (30 days, three "
        "months, six years) from the WORDS of the cited passage, never from memory; if no passage provided states "
        "the period, say that the period must be checked instead of stating one. Where the facts give the start "
        "date, work out the deadline and state it as 'D Month YYYY', citing the fact. "
        "If the material contains no provision on time limits, return an empty list rather than guessing.\n"
        "- evidence: the documents and evidence to obtain to prove the disputed facts, citing the fact paragraph "
        "each one goes to.\n"
        "- questions_for_client: 3-6 short questions about facts that are missing and would change the analysis."
    )

    async def run(self) -> CompiledBrief:
        s = self.session
        s.board.round = s.settings.debate_rounds + 1
        s.log(self.name, "start", f"{len(s.turns)} debate turns, {len(s.board.issues)} issues")
        raw = await self.with_fallback("compile", self._run_llm, self._run_offline)
        validator = CitationValidator(s.corpus, s.fact_sheet)
        raw_report: CitationReport = audit_brief(raw, validator)
        final, removed = guard_brief(raw, validator)
        s.log(self.name, "citation_guard", f"raw existence {raw_report.existence_rate:.2%}, {len(removed)} repair(s)")
        for ia in final.issues:  # carry the library-coverage verdict from the issue list into the brief
            bi = s.board.get(ia.issue_id)
            if bi:
                ia.coverage, ia.coverage_note = bi.coverage, bi.coverage_note
        if self.uses_llm and s.settings.verify_support:
            s.log("source_checker", "start", "checking that cited passages support each statement")
        final, _, support = await verify_brief(self, final)
        if support["mode"] != "off":
            s.log("source_checker", "done", f"{support['checked']} statements: {support['supported']} supported, "
                                            f"{support['partial']} partial, {support['unsupported']} unsupported; "
                                            f"{support['removed_precedents']} authorities removed")
        final.warnings = list(dict.fromkeys([*final.warnings, *s.warnings]))
        final_report = audit_brief(final, validator)
        for ia in final.issues:
            s.board.resolve(ia.issue_id, ia.assessment.text, self.name)
        s.log(self.name, "done", f"final claim coverage {final_report.coverage:.2%}")
        return CompiledBrief(raw=raw, final=final, raw_report=raw_report.as_dict(),
                             final_report=final_report.as_dict(), support_report=support)

    # ----------------------------------------------------------------- helpers
    def _entry(self, jid: str, stance: str) -> PrecedentEntry | None:
        j = self.session.corpus.get(jid)
        if not j:
            return None
        principle = self.session.corpus.passage(self.session.key_ref(jid)) or j.key_passage()
        return PrecedentEntry(judgment_id=j.id, case_name=j.name, citation=j.citation, stance=stance,  # type: ignore[arg-type]
                              proposition=CitedStatement(text=first_sentence(principle.text), citations=[principle.ref]))

    def _strength(self, issue: Issue, ids: list[str]) -> float:
        total = 0.0
        for jid in ids:
            j, c = self.session.corpus.get(jid), issue.candidate(jid)
            if j:
                total += j.court_weight * (0.5 + (c.score if c else 0.3))
        return total

    def _best_points(self, side: str, issue_id: str, cap: int = 4) -> list[CitedStatement]:
        """Keep the brief short: opening points first, then replies to the other side."""
        pts = [p for t in self.session.turns_by(side) for p in t.points if p.issue_id == issue_id]
        pts.sort(key=lambda p: p.responds_to is not None)
        return [CitedStatement(text=p.text, citations=p.citations) for p in pts[:cap]]

    def _ordered(self, issue: Issue, ids: list[str]) -> list[str]:
        return sorted(dict.fromkeys(ids), key=lambda jid: -(issue.candidate(jid).score if issue.candidate(jid) else 0))

    # ----------------------------------------------------------------- offline
    def _run_offline(self) -> Brief:
        s, f = self.session, self.session.facts
        client = f.claimant_label if f.client_role == "claimant" else f.defendant_label
        obj_ref = f.objective.citations[0]
        sections: list[IssueAnalysis] = []
        verdicts: list[str] = []
        summary = [CitedStatement(
            text=f"Acting for {client} ({f.client_role}), this brief addresses {len(s.board.issues)} issue(s) "
                 f"arising from {f.title}: {first_sentence(f.objective.text)}", citations=[obj_ref])]
        for issue in s.board.issues:
            sup_ids = self._ordered(issue, issue.supporting)
            opp_ids = self._ordered(issue, [j for j in issue.opposing if j not in issue.supporting] +
                                    [j for j in issue.opposing if j in issue.supporting])
            sup = [e for e in (self._entry(j, "supporting") for j in sup_ids) if e]
            opp = [e for e in (self._entry(j, "opposing") for j in opp_ids) if e]
            sup_pts, opp_pts = self._best_points("argument", issue.id), self._best_points("counter", issue.id)
            a, b = self._strength(issue, sup_ids), self._strength(issue, opp_ids)
            top_s, top_o = (sup[0] if sup else None), (opp[0] if opp else None)
            cites = [e.proposition.citations[0] for e in (top_s, top_o) if e]
            if a > 1.25 * b:
                verdict = "favourable"
                text = (f"Favourable: the authorities on balance support {client}"
                        + (f", led by {top_s.case_name}" if top_s else "")
                        + (f"; {top_o.case_name} is the main authority the other side will rely on." if top_o else "."))
            elif b > 1.25 * a:
                verdict = "unfavourable"
                text = (f"Unfavourable: the weight of authority is against {client}"
                        + (f", chiefly {top_o.case_name}" if top_o else "")
                        + (f"; the best answer is to rely on {top_s.case_name} and distinguish the facts." if top_s
                           else "; the facts must be distinguished."))
            else:
                verdict = "finely balanced"
                text = (f"Finely balanced: {top_s.case_name if top_s else 'the facts'} supports {client}, but "
                        f"{top_o.case_name if top_o else 'the evidence'} gives the other side a real argument; "
                        f"the outcome will turn on the facts the court accepts.")
            if not cites:
                cites = [s.best_fact(issue.question) or obj_ref]
            verdicts.append(verdict)
            summary.append(CitedStatement(text=f"{issue.question} {verdict.capitalize()} for {client}.", citations=cites))
            sections.append(IssueAnalysis(issue_id=issue.id, question=issue.question, supporting_precedents=sup,
                                          opposing_precedents=opp, supporting_argument=sup_pts,
                                          opposing_argument=opp_pts,
                                          assessment=CitedStatement(text=text, citations=cites)))
        fav, unf = verdicts.count("favourable"), verdicts.count("unfavourable")
        overall = "reasonable" if fav > unf else ("doubtful" if unf > fav else "evenly balanced")
        conclusion = [
            CitedStatement(text=f"Overall, {client}'s prospects look {overall} on the authorities retrieved "
                                f"({fav} favourable, {unf} unfavourable, {len(verdicts) - fav - unf} balanced issue(s)).",
                           citations=[c for sec in sections for c in sec.assessment.citations][:4] or [obj_ref]),
            CitedStatement(text="The disputed facts on which the outcome turns should be proved with evidence: "
                                + s.fact_text(s.best_fact("says argues relies denies disputes", prefer_defendant=True) or obj_ref),
                           citations=[s.best_fact("says argues relies denies disputes", prefer_defendant=True) or obj_ref]),
        ]
        facts = [CitedStatement(text=k.text, citations=k.citations) for k in f.key_facts]
        return Brief(case_id=f.case_id, title=f.title, acting_for=f.acting_for, summary=summary, facts=facts,
                     issues=sections, conclusion=conclusion)

    # --------------------------------------------------------------------- LLM
    async def _run_llm(self) -> Brief:
        s, f = self.session, self.session.facts
        debate = []
        for t in s.turns:
            debate.append(f"--- {t.speaker.upper()} round {t.round} ---")
            debate += [f"{p.point_id} [{p.issue_id}]{' (replies to ' + p.responds_to + ')' if p.responds_to else ''}: "
                       f"{p.text} CITES {p.citations}" for p in t.points]
        material = self._material()
        prompt = (f"{material}\n\nDEBATE TRANSCRIPT:\n" + "\n".join(debate)
                  + f"\n\nWrite the brief for the {f.acting_for}. Include every issue on the shared list, with its "
                    "precedents labelled 'supporting' or 'opposing' relative to the client. Two to four summary "
                    "statements and one to three conclusion statements.")
        out = await self.ask(prompt, BriefLLM)
        sections = []
        for sec in out.issues:
            sup, opp = [], []
            for p in sec.precedents:
                j = s.corpus.get(p.judgment_id)
                entry = PrecedentEntry(
                    judgment_id=p.judgment_id, case_name=j.name if j else p.judgment_id,
                    citation=j.citation if j else "", stance="supporting" if p.stance.startswith("support") else "opposing",
                    proposition=CitedStatement(text=p.proposition, citations=p.citations),
                    quote=(p.quote or "").strip().strip('"\u201c\u201d'))
                (sup if entry.stance == "supporting" else opp).append(entry)
            sections.append(IssueAnalysis(
                issue_id=sec.issue_id, question=sec.question, supporting_precedents=sup, opposing_precedents=opp,
                supporting_argument=[CitedStatement(**x.model_dump()) for x in sec.supporting_argument],
                opposing_argument=[CitedStatement(**x.model_dump()) for x in sec.opposing_argument],
                assessment=CitedStatement(**sec.assessment.model_dump())))
        return Brief(case_id=f.case_id, title=f.title, acting_for=f.acting_for,
                     summary=[CitedStatement(**x.model_dump()) for x in out.summary],
                     facts=[CitedStatement(text=k.text, citations=k.citations) for k in f.key_facts],
                     issues=sections, conclusion=[CitedStatement(**x.model_dump()) for x in out.conclusion],
                     remedies=[CitedStatement(**x.model_dump()) for x in out.remedies],
                     time_limits=[CitedStatement(**x.model_dump()) for x in out.time_limits],
                     evidence=[CitedStatement(**x.model_dump()) for x in out.evidence],
                     questions_for_client=[q.strip() for q in out.questions_for_client if q.strip()][:8])

    def _material(self) -> str:
        s = self.session
        lines = ["FACTS:"] + [f"[{p.ref}] {p.text}" for p in s.fact_sheet.paragraphs]
        lines += ["", "SHARED ISSUE LIST:", s.board.compact_view(s.corpus), "", "AUTHORITIES (citable passages):"]
        lines += s.authorities_block()
        extra = self._procedural_authorities()
        if extra:
            lines += ["", "REMEDIES AND TIME LIMITS (citable, mainly for the next-steps section):"]
            lines += s.authorities_block(only=extra)
        return "\n".join(lines)

    def _procedural_authorities(self) -> list[str]:
        """The provisions the next steps depend on: what each claim gets you (remedies, awards, orders)
        and when it must be brought (limitation, tribunal time limits). Retrieval for the issues looks for
        the law that decides liability, so these are searched for separately, per issue, in the matter's
        practice area. Returns authority ids not already on the issue list."""
        s = self.session
        area = s.fact_sheet.practice_area or None
        have = set(s.board.all_candidate_ids())
        new: list[str] = []
        for issue in s.board.issues:
            for intent in ("remedy: complaint to a tribunal or court, award, compensation, order, refund, damages",
                           "time limit: claim must be presented or brought within a period, limitation, months, years"):
                hits = s.retriever.search(f"{intent}. {issue.question}", top_k=2, kinds=("legislation",),
                                          prefer_area=area)
                for h in hits:
                    refs = s.extra_refs.setdefault(h.judgment_id, [])
                    refs += [p.ref for p in h.passages[:2] if p.ref not in refs]
                    if h.judgment_id not in have and h.judgment_id not in new:
                        new.append(h.judgment_id)
        s.log(self.name, "next_steps_research", f"{sum(len(v) for v in s.extra_refs.values())} remedy / time-limit passages")
        return new
