"""Fact Extractor Agent: structures the parties, dates and claims of a fact sheet,
and seeds the shared issue list with candidate issues."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel

from legal_brief.agents.base import BaseLegalAgent
from legal_brief.doctrines import AREA_LABELS, DOCTRINES, detect_doctrines, opposite, score_doctrines
from legal_brief.models import CitedStatement, ClaimItem, DatedEvent, Party, StructuredFacts

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
FULL_DATE = re.compile(rf"\b(\d{{1,2}} (?:{MONTHS}) \d{{4}})\b")
MONTH_YEAR = re.compile(rf"\b((?:{MONTHS}) \d{{4}})\b")


# ----------------------------------------------------------------- LLM schema
class _LLMParty(BaseModel):
    name: str
    role: str
    description: str


class _LLMEvent(BaseModel):
    date: str
    event: str
    fact_ref: str


class _LLMClaim(BaseModel):
    claimant: str
    respondent: str
    claim: str
    legal_basis: str
    fact_refs: list[str]


class _LLMStatement(BaseModel):
    text: str
    citations: list[str]


class _LLMIssue(BaseModel):
    question: str
    doctrine: str
    reason: str


class FactExtractionLLM(BaseModel):
    client_role: str
    parties: list[_LLMParty]
    chronology: list[_LLMEvent]
    claims: list[_LLMClaim]
    key_facts: list[_LLMStatement]
    candidate_issues: list[_LLMIssue]


def _iso(date: str) -> str | None:
    for fmt in ("%d %B %Y", "%B %Y"):
        try:
            return datetime.strptime(date.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


class FactExtractorAgent(BaseLegalAgent):
    name = "fact_extractor"
    description = "Structures the parties, dates and claims in a case fact sheet."
    tool_profile = "none"
    instructions = (
        "You are the Fact Extractor in a legal briefing team ({jurisdiction}). Read a case fact sheet whose "
        "paragraphs are labelled [F1], [F2], ... and structure it.\n"
        "- parties: every person or company, with role claimant, defendant or third party.\n"
        "- chronology: every dated event in date order; date exactly as written; fact_ref is the [F#] it comes from.\n"
        "- claims: what the client claims, against whom, and the legal basis (e.g. negligence, breach of contract).\n"
        "- key_facts: 5-9 short factual statements, each citing the [F#] refs that support it, e.g. citations ['F2'].\n"
        "- candidate_issues: the legal issues a SPECIALIST solicitor in this practice area would identify, phrased "
        "as yes/no questions that name the cause of action or defence and, where it is statutory, the provision "
        "(e.g. 'Was Mr X automatically unfairly dismissed for making a protected disclosure (ERA 1996 s 103A)?', "
        "'Can Ms Y reject the goods and claim a full refund under the short-term right to reject (CRA 2015 s 22)?'). "
        "Cover every claim in the client's objective and the main defence. Do NOT frame statutory employment, "
        "consumer or tenancy claims as negligence 'duty of care' questions; raise negligence only where the facts "
        "disclose a free-standing tort claim. Give each issue one doctrine key from this list: "
        f"{', '.join(DOCTRINES)}.\n"
        "Frame issues under the law of {jurisdiction} only, using its own concepts and remedies (for example, "
        "in an Indian land dispute: title, possession, boundary demarcation and revenue records, not English "
        "negligence). Never invent facts. Use only F refs that exist. Do not cite case law here."
    )

    async def run(self) -> StructuredFacts:
        fs = self.session.fact_sheet
        self.session.log(self.name, "start", f"{fs.case_id}: {len(fs.paragraphs)} paragraphs")
        facts, issues = await self.with_fallback("extract", self._run_llm, self._run_offline)
        self.session.facts = facts
        position_flip = facts.client_role == "defendant"
        for question, doctrine, reason in issues:
            d = DOCTRINES.get(doctrine)
            pos = d.claimant_wants if d else "pro"
            self.session.board.add_issue(question, doctrine if d else None, self.name,
                                         opposite(pos) if position_flip else pos, reason)
        self.session.log(self.name, "done", f"{len(facts.parties)} parties, {len(facts.chronology)} dated events, "
                                            f"{len(facts.claims)} claims, {len(issues)} candidate issues")
        return facts

    # ----------------------------------------------------------------- offline
    def _run_offline(self) -> tuple[StructuredFacts, list[tuple[str, str, str]]]:
        fs = self.session.fact_sheet
        parties = []
        for line in fs.parties_block:
            m = re.match(r"([^:]+):\s*([^,]+?)(?:,\s*(.*))?$", line)
            if m:
                role, name, desc = m.group(1).strip().lower(), m.group(2).strip().rstrip("."), (m.group(3) or "").strip()
                parties.append(Party(name=name, role=role, description=desc))
        client_role = "defendant" if "defend" in fs.acting_for.lower() else "claimant"

        chronology: list[DatedEvent] = []
        for p in fs.paragraphs:
            sentences = re.split(r"(?<=[.!?])\s+", p.text)
            for s in sentences:
                dates = FULL_DATE.findall(s) or MONTH_YEAR.findall(s)
                for d in dates:
                    chronology.append(DatedEvent(date=d, iso_date=_iso(d), event=s.strip(), fact_ref=p.ref))
        chronology.sort(key=lambda e: e.iso_date or "9999")

        objective_p = next((p for p in fs.paragraphs if p.kind == "objective"), fs.paragraphs[-1])
        detected = detect_doctrines(fs.raw_text)
        claimants = [p.name for p in parties if p.role.startswith("claimant")] or ["Claimant"]
        defendants = [p.name for p in parties if p.role.startswith("defendant")] or ["Defendant"]
        areas = sorted({DOCTRINES[k].area for k, _ in detected})
        basis = " / ".join(AREA_LABELS.get(a, a.title()) for a in areas) or "Unclassified"

        def related_facts(doctrine: str) -> list[str]:
            pats = DOCTRINES[doctrine].patterns
            scored = [(sum(bool(re.search(pt, p.text.lower())) for pt in pats), p.ref)
                      for p in fs.paragraphs if p.kind == "fact"]
            return [ref for s, ref in sorted(scored, key=lambda x: -x[0]) if s > 0][:3]

        claims = [ClaimItem(claimant=" and ".join(claimants), respondent=" and ".join(defendants),
                            claim=re.split(r"(?<=[.!?])\s+", objective_p.text)[0], legal_basis=basis,
                            fact_refs=sorted({r for k, _ in detected for r in related_facts(k)},
                                             key=lambda r: int(r[1:])))]
        key_facts = [CitedStatement(text=p.text, citations=[p.ref]) for p in fs.paragraphs if p.kind == "fact"]
        facts = StructuredFacts(
            case_id=fs.case_id, title=fs.title, acting_for=fs.acting_for, client_role=client_role,
            parties=parties, chronology=chronology, claims=claims, key_facts=key_facts,
            objective=CitedStatement(text=objective_p.text, citations=[objective_p.ref]),
        )
        claimant, defendant = facts.claimant_label, facts.defendant_label
        issues = [(DOCTRINES[k].frame(claimant, defendant), k, f"{s} cue(s) in the fact sheet") for k, s in detected]
        return facts, issues

    # --------------------------------------------------------------------- LLM
    async def _run_llm(self) -> tuple[StructuredFacts, list[tuple[str, str, str]]]:
        fs = self.session.fact_sheet
        out = await self.ask("Structure this fact sheet.\n\n" + fs.numbered_text(), FactExtractionLLM)
        valid_refs = {p.ref for p in fs.paragraphs}
        keep = lambda refs: [r.strip("[] ") for r in refs if r.strip("[] ") in valid_refs]  # noqa: E731
        objective_p = next((p for p in fs.paragraphs if p.kind == "objective"), fs.paragraphs[-1])
        role = "defendant" if "defend" in (out.client_role or fs.acting_for).lower() else "claimant"
        facts = StructuredFacts(
            case_id=fs.case_id, title=fs.title, acting_for=fs.acting_for, client_role=role,
            parties=[Party(name=p.name, role=p.role.lower(), description=p.description) for p in out.parties],
            chronology=sorted(
                [DatedEvent(date=e.date, iso_date=_iso(e.date), event=e.event, fact_ref=e.fact_ref.strip("[] "))
                 for e in out.chronology if e.fact_ref.strip("[] ") in valid_refs],
                key=lambda e: e.iso_date or "9999"),
            claims=[ClaimItem(claimant=c.claimant, respondent=c.respondent, claim=c.claim,
                              legal_basis=c.legal_basis, fact_refs=keep(c.fact_refs)) for c in out.claims],
            key_facts=[CitedStatement(text=k.text, citations=keep(k.citations)) for k in out.key_facts if keep(k.citations)],
            objective=CitedStatement(text=objective_p.text, citations=[objective_p.ref]),
        )
        issues = [(i.question, i.doctrine if i.doctrine in DOCTRINES else "", i.reason) for i in out.candidate_issues]
        if not issues:  # never start a debate with an empty issue list
            issues = [(DOCTRINES[k].frame(facts.claimant_label, facts.defendant_label), k, "baseline detector")
                      for k, _ in detect_doctrines(fs.raw_text)]
        self.session.log(self.name, "llm_extract", f"doctrine cue scores: {score_doctrines(fs.raw_text)}")
        return facts, issues
