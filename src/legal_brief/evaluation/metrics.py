"""Evaluation metrics for one case.

* Precedent recall (retrieval): share of known relevant precedents that the
  Precedent Retrieval Agent put on the shared issue list.
* Precedent recall (brief): share of known relevant precedents the final brief cites.
* Citation existence: share of citations in the brief that exist in the corpus
  (or the fact sheet), measured on the compiler's raw output before the citation
  guard and again on the final brief. Free-text case names count as citations.
* Claim coverage: share of statements in the final brief with a verified citation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class CaseMetrics:
    case_id: str
    gold: list[str]
    retrieved: list[str]
    cited: list[str]
    retrieval_recall: float
    brief_recall: float
    gold_precision: float  # share of cited judgments that are in the gold list (informative only)
    citation_existence_raw: float
    citation_existence_final: float
    judgment_citation_existence_raw: float
    claim_coverage: float
    citations_raw: int
    citations_final: int
    statements: int
    issues: int
    llm_calls: int
    seconds: float
    missed: list[str] = field(default_factory=list)
    retrieval_recall_text_only: float | None = None
    warnings: int = 0
    llm_fallbacks: int = 0  # agent steps that fell back to the offline baseline
    content_filtered: bool = False  # the provider's content filter blocked requests

    def as_dict(self) -> dict:
        return asdict(self)


def _recall(gold: list[str], found: list[str]) -> float:
    return sum(1 for g in gold if g in found) / len(gold) if gold else 1.0


def score_case(result, gold: list[str]) -> CaseMetrics:
    s, c = result.session, result.compiled
    retrieved = s.board.all_candidate_ids()
    cited = c.final_report["cited_judgments"]
    raw, final = c.raw_report, c.final_report
    jraw = raw["valid_judgment_citations"] / raw["judgment_citations"] if raw["judgment_citations"] else 1.0
    return CaseMetrics(
        case_id=s.fact_sheet.case_id, gold=gold, retrieved=retrieved, cited=cited,
        retrieval_recall=_recall(gold, retrieved), brief_recall=_recall(gold, cited),
        gold_precision=(sum(1 for j in cited if j in gold) / len(cited)) if cited else 0.0,
        citation_existence_raw=raw["existence_rate"], citation_existence_final=final["existence_rate"],
        judgment_citation_existence_raw=round(jraw, 4), claim_coverage=final["claim_coverage"],
        citations_raw=raw["total_citations"], citations_final=final["total_citations"],
        statements=final["statements"], issues=len(s.board.issues), llm_calls=s.llm_calls,
        seconds=round(result.seconds, 3), missed=[g for g in gold if g not in cited],
        warnings=len(c.final.warnings),
        llm_fallbacks=sum("LLM step" in w for w in s.warnings),
        content_filtered=any("ContentFilter" in w for w in s.warnings),
    )
