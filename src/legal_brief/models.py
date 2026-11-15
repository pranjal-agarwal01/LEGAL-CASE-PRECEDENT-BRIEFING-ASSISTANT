"""Domain models shared by all agents (pydantic, so they serialise cleanly)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["argument", "counter"]
Stance = Literal["supporting", "opposing"]


class CitedStatement(BaseModel):
    """A single claim in the brief together with the citations that ground it.

    Citation ids: "J01:p2" (judgment J01, passage p2), "J01" (whole judgment)
    or "F3" (paragraph 3 of the fact sheet).
    """

    text: str
    citations: list[str] = Field(default_factory=list)


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
    raw_text: str
    parties_block: list[str] = Field(default_factory=list)
    paragraphs: list[FactParagraph] = Field(default_factory=list)

    def paragraph(self, ref: str) -> FactParagraph | None:
        return next((p for p in self.paragraphs if p.ref == ref), None)

    def numbered_text(self) -> str:
        lines = [f"# {self.title}", f"Acting for: {self.acting_for}", "", "Parties:"]
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


class IssueAnalysis(BaseModel):
    issue_id: str
    question: str
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
    warnings: list[str] = Field(default_factory=list)

    def statements(self) -> list[CitedStatement]:
        """Every claim in the brief, in reading order."""
        out: list[CitedStatement] = [*self.summary, *self.facts]
        for issue in self.issues:
            out += [p.proposition for p in issue.supporting_precedents]
            out += [p.proposition for p in issue.opposing_precedents]
            out += issue.supporting_argument + issue.opposing_argument + [issue.assessment]
        return out + self.conclusion
