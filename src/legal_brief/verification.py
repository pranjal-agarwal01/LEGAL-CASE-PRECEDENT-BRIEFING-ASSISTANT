"""Source-support check: does each cited passage actually say what the brief claims?

The citation guard only proves that a cited authority exists. This step reads the
cited passages next to every statement that relies on law and grades it:

    supported    the passages state the proposition (or it follows directly)
    partial      the passages are relevant but the statement goes beyond them
    unsupported  the passages do not say this (wrong authority, invented holding)

Precedent entries whose proposition is unsupported are removed from the brief.
Other unsupported statements stay, clearly flagged, because the reasoning may
still be useful to the lawyer, but they are never presented as verified.
An issue left with no supported authority is marked as not covered by the library.

In offline mode statements are left "unchecked".
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel

from legal_brief.citations import normalise, resolve_passage
from legal_brief.models import Brief, CitedStatement

log = logging.getLogger(__name__)
BATCH = 18
PASSAGE_CHARS = 1400

INSTRUCTIONS = (
    "You are a meticulous legal source checker (England and Wales). For each statement you get the exact text of "
    "the passages it cites. Decide whether those passages support the statement's LEGAL content.\n"
    "- supported: the passages state the legal proposition, or it follows directly from their words.\n"
    "- partial: the passages are on point but the statement adds something they do not say (a broader rule, a "
    "different test, a conclusion the passage does not reach), or relies on a fact paragraph for part of it.\n"
    "- unsupported: the passages do not say this, are about a different area of law, or are cited for a holding "
    "they do not contain.\n"
    "Applying a stated rule to the client's facts is fine and counts as supported when the rule itself is in the "
    "passage. Judge only against the passage text given, not your own knowledge. Keep each note under 25 words "
    "and say what is missing when the verdict is not 'supported'."
)


class _Verdict(BaseModel):
    id: str
    verdict: Literal["supported", "partial", "unsupported"]
    note: str


class SupportCheckLLM(BaseModel):
    verdicts: list[_Verdict]


def _authority_cites(st: CitedStatement) -> list[str]:
    return [c for c in st.citations if c[:1] in "JLU" and c[1:2].isdigit()]


def _passages_text(session, cites: list[str]) -> list[dict]:
    out = []
    for c in cites:
        c = normalise(c)
        jid, _, pid = c.partition(":")
        j = session.corpus.get(jid)
        if not j:
            continue
        if pid:
            p = resolve_passage(session.corpus, jid, pid)
            ps = [p] if p else []
            if p and p.pid != pid:  # whole section cited: include every part
                ps = [q for q in j.passages if q.pid == pid or q.pid.startswith(pid + ".")]
        else:
            ps = [j.key_passage()]
        for p in ps:
            out.append({"ref": p.ref, "authority": j.full_name, "where": p.display, "text": p.text[:PASSAGE_CHARS]})
    return out


def _facts_text(session, st: CitedStatement) -> list[str]:
    return [f"[{c}] {session.fact_sheet.paragraph(c).text[:600]}" for c in st.citations
            if c.startswith("F") and session.fact_sheet.paragraph(c)]


async def verify_brief(agent, brief: Brief) -> tuple[Brief, list[str], dict]:
    """Grade every statement that cites authority; returns (brief, warnings, stats). `agent` is the
    BriefCompilerAgent (for its session and LLM access)."""
    s = agent.session
    out = brief.model_copy(deep=True)
    statements: list[tuple[str, CitedStatement, str]] = []  # (id, statement, role)
    for st in out.summary + out.facts + out.conclusion:
        statements.append(("", st, "statement"))
    for issue in out.issues:
        for e in issue.supporting_precedents + issue.opposing_precedents:
            # A precedent's proposition must be checked against that authority's own text.
            if not any(c.split(":")[0] == e.judgment_id for c in e.proposition.citations):
                e.proposition.citations = [s.key_ref(e.judgment_id, s.board.get(issue.issue_id)),
                                           *e.proposition.citations]
            statements.append(("", e.proposition, f"precedent:{issue.issue_id}:{e.judgment_id}"))
        for st in issue.supporting_argument + issue.opposing_argument + [issue.assessment]:
            statements.append(("", st, "statement"))
    to_check = []
    for n, (_, st, role) in enumerate(statements, 1):
        if not _authority_cites(st):
            st.support = "facts_only" if st.citations else "unchecked"
            continue
        to_check.append((f"S{n}", st, role))

    stats = {"checked": 0, "supported": 0, "partial": 0, "unsupported": 0, "removed_precedents": 0,
             "mode": "llm" if agent.uses_llm and s.settings.verify_support else "off"}
    if not to_check or stats["mode"] == "off":
        return out, [], stats

    verdicts: dict[str, _Verdict] = {}
    for start in range(0, len(to_check), BATCH):
        batch = to_check[start:start + BATCH]
        payload = [{"id": sid, "statement": st.text, "cited_passages": _passages_text(s, _authority_cites(st)),
                    "cited_facts": _facts_text(s, st)} for sid, st, _ in batch]
        prompt = ("Grade each statement against its cited passages.\n\n" + json.dumps(payload, ensure_ascii=False))
        try:
            res = await agent.ask_as("source_checker", INSTRUCTIONS, prompt, SupportCheckLLM)
            verdicts.update({v.id: v for v in res.verdicts})
        except Exception as e:  # noqa: BLE001 - an unchecked statement is shown as unchecked, never as verified
            s.warnings.append(f"Source check could not run for {len(batch)} statement(s) ({type(e).__name__}); "
                              "they are marked unchecked.")
            log.warning("support check failed: %s", e)

    warnings: list[str] = []
    drop: set[tuple[str, str]] = set()
    for sid, st, role in to_check:
        v = verdicts.get(sid)
        if not v:
            continue
        st.support, st.support_note = v.verdict, v.note.strip()
        stats["checked"] += 1
        stats[v.verdict] += 1
        if v.verdict == "unsupported" and role.startswith("precedent:"):
            _, issue_id, jid = role.split(":")
            drop.add((issue_id, jid))
            warnings.append(f"Removed {jid} from {issue_id}: its cited passage does not support "
                            f"'{st.text[:90]}' ({v.note.strip()})")
    for issue in out.issues:
        for attr in ("supporting_precedents", "opposing_precedents"):
            kept = [e for e in getattr(issue, attr) if (issue.issue_id, e.judgment_id) not in drop]
            stats["removed_precedents"] += len(getattr(issue, attr)) - len(kept)
            setattr(issue, attr, kept)
        authorities = issue.supporting_precedents + issue.opposing_precedents
        backed = [e for e in authorities if e.proposition.support in ("supported", "partial")]
        if not backed and issue.coverage != "none":
            issue.coverage = "none"
            issue.coverage_note = issue.coverage_note or (
                "No authority in the library was verified as supporting either side of this issue. Research it "
                "independently.")
        elif backed and len(backed) < 2 and issue.coverage == "good":
            issue.coverage = "weak"
            issue.coverage_note = issue.coverage_note or "Only one verified authority on this issue."
    out.warnings = list(dict.fromkeys([*out.warnings, *warnings]))
    return out, warnings, stats
