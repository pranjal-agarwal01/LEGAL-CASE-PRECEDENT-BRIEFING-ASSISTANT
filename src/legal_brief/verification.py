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
import re
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
    "passage. Judge support only against the passage text given.\n"
    "Separately grade relevance to the ISSUE shown with the statement, using your knowledge of the law of England "
    "and Wales: 'on_point' if a specialist would cite it for this issue, 'analogous' if it is a reasonable "
    "analogy, 'off_point' if it comes from a different area of law, does not govern this kind of claim (for "
    "example the Sale of Goods Act 1979 for a consumer contract made after 1 October 2015, or a negligence case "
    "for a statutory employment right), or is only tangential. Keep each note under 25 words and say what is "
    "missing or why it is off point. "
    "Statements of kind 'time_limit' are deadlines a lawyer will diary: grade them 'supported' only if a cited "
    "passage states that exact period for that exact right or claim (a period that applies to a different right, "
    "or a presumption period that is not a deadline, makes it 'unsupported'), and check that any date given is "
    "counted correctly from the facts."
)


class _Verdict(BaseModel):
    id: str
    verdict: Literal["supported", "partial", "unsupported"]
    relevance: Literal["on_point", "analogous", "off_point"]
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


def _norm(text: str) -> str:
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    return re.sub(r"[^a-z0-9'\"-]+", " ", text).strip()


_STOP = set("""a an and are as at be by for from has have in is it its of on or that the this to was were which
with not no any may must shall such than their there these they under where who will""".split())


def _words(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) > 2 and w not in _STOP}


def _best_sentence(pairs: list[tuple[str, str]], claim: str) -> tuple[str, str] | None:
    """(ref, sentence): the sentence of the cited passages sharing most content words with the claim,
    if it shares enough of them to be the obvious source."""
    want = _words(claim)
    best, best_score = None, 0.0
    for ref, text in pairs:
        for sent in re.split(r"(?<=[.;:])\s+|\n+", text):
            sent = sent.strip(" -\t")
            n = len(sent.split())
            if n < 6 or n > 70:
                continue
            got = _words(sent)
            score = len(want & got) / (len(got) ** 0.5 + 1)
            if score > best_score:
                best, best_score = (ref, sent), score
    if not best or len(want & _words(best[1])) < 3:
        return None
    return best


def check_quotes(session, brief: Brief) -> dict:
    """Mark each precedent's quote verified only if its words appear verbatim in the cited passage
    (ignoring case, punctuation and line breaks). Unverifiable quotes are removed, never shown as quotes."""
    stats = {"quotes": 0, "verified": 0, "removed": 0}
    for issue in brief.issues:
        for e in issue.supporting_precedents + issue.opposing_precedents:
            if not e.quote.strip():
                continue
            stats["quotes"] += 1
            j = session.corpus.get(e.judgment_id)
            refs = [e.quote_ref] if e.quote_ref else []
            refs += [c for c in e.proposition.citations if c.split(":")[0] == e.judgment_id]
            pairs = []  # (ref, passage text) to search
            for r in dict.fromkeys(normalise(x) for x in refs):
                jid, _, pid = r.partition(":")
                if j and pid:
                    pairs += [(f"{jid}:{p.pid}", p.text) for p in j.passages if p.pid == pid or p.pid.startswith(pid + ".")]
            if not pairs and j:
                pairs = [(p.ref, p.text) for p in j.passages]
            needle = _norm(e.quote)
            hit = next((r for r, t in pairs if needle and needle in _norm(t)), None)
            if hit and len(needle.split()) >= 4:
                e.quote_verified, e.quote_ref = True, hit
                stats["verified"] += 1
                continue
            # Not verbatim: quote instead the sentence of the cited passage that best matches the claim.
            # It is copied from the source, so it is verbatim by construction.
            best = _best_sentence(pairs, f"{e.quote} {e.proposition.text}")
            if best:
                e.quote, e.quote_ref, e.quote_verified = best[1], best[0], True
                stats["replaced"] = stats.get("replaced", 0) + 1
            else:
                e.quote, e.quote_ref, e.quote_verified = "", "", False
                stats["removed"] += 1
    return stats


async def verify_brief(agent, brief: Brief) -> tuple[Brief, list[str], dict]:
    """Grade every statement that cites authority; returns (brief, warnings, stats). `agent` is the
    BriefCompilerAgent (for its session and LLM access)."""
    s = agent.session
    out = brief.model_copy(deep=True)
    statements: list[tuple[str, CitedStatement, str]] = []  # (id, statement, role)
    for st in out.summary + out.facts + out.conclusion + out.remedies + out.evidence:
        statements.append(("", st, "statement"))
    for st in out.time_limits:
        statements.append(("", st, "time_limit"))
    for issue in out.issues:
        for e in issue.supporting_precedents + issue.opposing_precedents:
            # A precedent's proposition must be checked against that authority's own text.
            if not any(c.split(":")[0] == e.judgment_id for c in e.proposition.citations):
                e.proposition.citations = [s.key_ref(e.judgment_id, s.board.get(issue.issue_id)),
                                           *e.proposition.citations]
            statements.append(("", e.proposition, f"precedent:{issue.issue_id}:{e.judgment_id}:{e.stance}"))
        for st in issue.supporting_argument + issue.opposing_argument + [issue.assessment]:
            statements.append(("", st, f"arg:{issue.issue_id}"))
    to_check = []
    for n, (_, st, role) in enumerate(statements, 1):
        if not _authority_cites(st):
            st.support = "facts_only" if st.citations else "unchecked"
            continue
        to_check.append((f"S{n}", st, role))

    stats = {"checked": 0, "supported": 0, "partial": 0, "unsupported": 0, "removed_precedents": 0,
             "mode": "llm" if agent.uses_llm and s.settings.verify_support else "off"}
    stats["quotes"] = check_quotes(s, out)
    if not to_check or stats["mode"] == "off":
        return out, [], stats

    verdicts: dict[str, _Verdict] = {}
    issue_text = {i.issue_id: i.question for i in out.issues}
    for start in range(0, len(to_check), BATCH):
        batch = to_check[start:start + BATCH]
        payload = [{"id": sid, "kind": "time_limit" if role == "time_limit" else "statement",
                    "issue": issue_text.get(role.split(":")[1], "") if role.startswith(("precedent", "arg")) else "",
                    "statement": st.text, "cited_passages": _passages_text(s, _authority_cites(st)),
                    "cited_facts": _facts_text(s, st)} for sid, st, role in batch]
        prompt = ("Grade each statement against its cited passages.\n\n" + json.dumps(payload, ensure_ascii=False))
        try:
            res = await agent.ask_as("source_checker", INSTRUCTIONS, prompt, SupportCheckLLM)
            verdicts.update({v.id: v for v in res.verdicts})
        except Exception as e:  # noqa: BLE001 - an unchecked statement is shown as unchecked, never as verified
            s.warnings.append(f"Source check could not run for {len(batch)} statement(s) ({type(e).__name__}); "
                              "they are marked unchecked.")
            log.warning("support check failed: %s", e)

    warnings: list[str] = []
    drop: set[tuple[str, str, str]] = set()  # (issue, authority, stance): only the side that failed
    for sid, st, role in to_check:
        v = verdicts.get(sid)
        if not v:
            continue
        verdict = v.verdict
        if v.relevance == "off_point" and role.startswith("precedent:"):
            verdict = "unsupported"  # an authority from the wrong area of law must not be presented as support
            stats["off_point"] = stats.get("off_point", 0) + 1
        st.support, st.support_note = verdict, v.note.strip()
        stats["checked"] += 1
        stats[verdict] += 1
        if verdict == "unsupported" and role.startswith("precedent:"):
            _, issue_id, jid, stance = role.split(":")
            drop.add((issue_id, jid, stance))
            why = "it is off point for this issue" if v.relevance == "off_point" and v.verdict != "unsupported" \
                else "its cited passage does not support"
            warnings.append(f"Removed {jid} from {issue_id}: {why} '{st.text[:90]}' ({v.note.strip()})")
    for issue in out.issues:
        for attr in ("supporting_precedents", "opposing_precedents"):
            kept = [e for e in getattr(issue, attr) if (issue.issue_id, e.judgment_id, e.stance) not in drop]
            stats["removed_precedents"] += len(getattr(issue, attr)) - len(kept)
            setattr(issue, attr, kept)
        authorities = issue.supporting_precedents + issue.opposing_precedents
        backed = [e for e in authorities if e.proposition.support in ("supported", "partial")]
        # Arguments and the assessment count too when the law they cite was verified.
        argued = [st for st in issue.supporting_argument + issue.opposing_argument + [issue.assessment]
                  if st.support == "supported" and _authority_cites(st)]
        if not backed and not argued and issue.coverage != "none":
            issue.coverage = "none"
            issue.coverage_note = issue.coverage_note or (
                "No authority in the library was verified as supporting either side of this issue. Research it "
                "independently.")
        elif not backed and argued and issue.coverage == "good":
            issue.coverage = "weak"
            issue.coverage_note = issue.coverage_note or (
                "The arguments rest on verified provisions, but no authority was confirmed for the precedent lists.")
        elif backed and len(backed) < 2 and not argued and issue.coverage == "good":
            issue.coverage = "weak"
            issue.coverage_note = issue.coverage_note or "Only one verified authority on this issue."
    out.warnings = list(dict.fromkeys([*out.warnings, *warnings]))
    return out, warnings, stats
