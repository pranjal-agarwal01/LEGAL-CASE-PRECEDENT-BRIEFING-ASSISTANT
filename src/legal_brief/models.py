"""Domain models shared by all agents (pydantic, so they serialise cleanly)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AREA_NAMES = {"contract": "contract and consumer law", "tort": "tort and personal injury",
              "property": "landlord and tenant", "employment": "employment law"}

Side = Literal["argument", "counter"]
Stance = Literal["supporting", "opposing"]
Support = Literal["supported", "partial", "unsupported", "unchecked", "facts_only"]


class CitedStatement(BaseModel):
    """A single claim in the brief together with the citations that ground it.

    Citation ids: "J01:p2" (judgment J01, passage p2), "J01" (whole judgment)
    or "F3" (paragraph 3 of the fact sheet).
    """

    text: str
    citations: list[str] = Field(default_factory=list)
    # Set by the source-support check: does the cited material actually say this?
    support: Support = "unchecked"
    support_note: str = ""


# ---------------------------------------------------------------- fact sheet

class FactParagraph(BaseModel):
    ref: str  # "F1"
    kind: Literal["fact", "objective"] = "fact"
    text: str


class FactSheet(BaseModel):
    case_id: str
    title: str
    acting_for: str
    source_path: str = ""
    practice_area: str = ""  # contract | tort | property | employment | "" (unknown)
    raw_text: str
    parties_block: list[str] = Field(default_factory=list)
    paragraphs: list[FactParagraph] = Field(default_factory=list)

    def paragraph(self, ref: str) -> FactParagraph | None:
        return next((p for p in self.paragraphs if p.ref == ref), None)

    def numbered_text(self) -> str:
        lines = [f"# {self.title}", f"Acting for: {self.acting_for}"]
        if self.practice_area:
            lines.append(f"Practice area: {AREA_NAMES.get(self.practice_area, self.practice_area)}")
        lines += ["", "Parties:"]
        lines += [f"- {p}" for p in self.parties_block]
        lines.append("")
        lines += [f"[{p.ref}] ({p.kind}) {p.text}" for p in self.paragraphs]
        return "\n".join(lines)


# ---------------------------------------------------------- fact extraction

class Party(BaseModel):
    name: str
    role: str  # claimant / defendant / third party / ...
    description: str = ""


class DatedEvent(BaseModel):
    date: str
    iso_date: str | None = None
    event: str
    fact_ref: str


class ClaimItem(BaseModel):
    claimant: str
    respondent: str
    claim: str
    legal_basis: str
    fact_refs: list[str] = Field(default_factory=list)


class StructuredFacts(BaseModel):
    case_id: str
    title: str
    acting_for: str
    client_role: Literal["claimant", "defendant"]
    parties: list[Party]
    chronology: list[DatedEvent]
    claims: list[ClaimItem]
    key_facts: list[CitedStatement]
    objective: CitedStatement

    def names(self, role: str) -> list[str]:
        return [p.name for p in self.parties if p.role.lower().startswith(role)]

    @property
    def claimant_label(self) -> str:
        return " and ".join(self.names("claimant")) or "the claimant"

    @property
    def defendant_label(self) -> str:
        return " and ".join(self.names("defendant")) or "the defendant"


# ------------------------------------------------------------------ debate

class ArgumentPoint(BaseModel):
    point_id: str = ""
    issue_id: str
    text: str
    citations: list[str] = Field(default_factory=list)
    responds_to: str | None = None


class DebateTurn(BaseModel):
    speaker: Side
    round: int
    points: list[ArgumentPoint] = Field(default_factory=list)
    mode: str = "offline"


# ------------------------------------------------------------------- brief

class PrecedentEntry(BaseModel):
    judgment_id: str
    case_name: str
    citation: str
    stance: Stance
    proposition: CitedStatement
    # The exact words relied on, and whether they were found verbatim in the cited passage
    # (a deterministic text match, not a model judgement).
    quote: str = ""
    quote_ref: str = ""
    quote_verified: bool = False


class IssueAnalysis(BaseModel):
    issue_id: str
    question: str
    # How well the library covers this issue: good | weak | none (set by retrieval)
    coverage: str = "good"
    coverage_note: str = ""
    supporting_precedents: list[PrecedentEntry] = Field(default_factory=list)
    opposing_precedents: list[PrecedentEntry] = Field(default_factory=list)
    supporting_argument: list[CitedStatement] = Field(default_factory=list)
    opposing_argument: list[CitedStatement] = Field(default_factory=list)
    assessment: CitedStatement


class Brief(BaseModel):
    case_id: str
    title: str
    acting_for: str
    summary: list[CitedStatement] = Field(default_factory=list)
    facts: list[CitedStatement] = Field(default_factory=list)
    issues: list[IssueAnalysis] = Field(default_factory=list)
    conclusion: list[CitedStatement] = Field(default_factory=list)
    # Next steps for the lawyer: every item cites law or facts and is source-checked like the rest.
    remedies: list[CitedStatement] = Field(default_factory=list)
    time_limits: list[CitedStatement] = Field(default_factory=list)
    evidence: list[CitedStatement] = Field(default_factory=list)
    questions_for_client: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def statements(self) -> list[CitedStatement]:
        """Every claim in the brief, in reading order."""
        out: list[CitedStatement] = [*self.summary, *self.facts]
        for issue in self.issues:
            out += [p.proposition for p in issue.supporting_precedents]
            out += [p.proposition for p in issue.opposing_precedents]
            out += issue.supporting_argument + issue.opposing_argument + [issue.assessment]
        return out + self.conclusion + self.remedies + self.time_limits + self.evidence
