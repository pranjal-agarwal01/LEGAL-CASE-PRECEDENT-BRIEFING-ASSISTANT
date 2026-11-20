"""Citation ids, validation against the library, rendering and the citation guard.

Citation ids used throughout the system:
    J01:p2   passage p2 of case summary J01          J01   the authority as a whole
    L01:s62  section 62 of statute L01 (s11.2 = part 2 of a long section; s11 = the whole section)
    U12:p45  paragraph 45 of uploaded judgment U12
    F3       paragraph 3 of the fact sheet
Free-text case names in a statement ("... as in Smith v Jones ...") are also
checked: a name that matches no judgment in the library counts as a citation that
does not exist. Statute names ("... Housing Act 2004 ...") that are not in the
library produce a warning.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from legal_brief.corpus import Corpus
from legal_brief.models import Brief, CitedStatement, FactSheet

_AUTH = r"[JLU]\d{1,6}"
_PID = r"[a-z]{1,3}\d+[A-Za-z]*(?:\.\d+)?"
CITE_RE = re.compile(rf"^(?:({_AUTH})(?::({_PID}))?|F(\d+))$")
_ONE = rf"(?:{_AUTH}(?::{_PID})?|F\d+)"
# Citation ids written into the prose, in square brackets or parentheses: "[J06:p3]", "(L23:s213.1, F7)".
INLINE_CITE_RE = re.compile(rf"[\[(]({_ONE}(?:\s*[,;]\s*{_ONE})*)[\])]")
# Passage ids anywhere in the prose (an id with a colon is never ordinary English).
BARE_ID_RE = re.compile(rf"(?<![\w:])({_AUTH}:{_PID})(?![\w.])")
_FACT_WORD_RE = re.compile(r"(?:\bfacts?\s+)?(?<![\w])F\d+(?![\w])")


def strip_ids(text: str) -> str:
    """Remove citation ids from a statement's prose (they are shown as formatted citations instead)."""
    t = INLINE_CITE_RE.sub("", text)
    if BARE_ID_RE.search(t):
        t = BARE_ID_RE.sub("", t)
        t = _FACT_WORD_RE.sub("", t)  # "facts F1" left inside the same parenthesis
    prev = None
    while prev != t:  # tidy the punctuation the removals leave behind, until nothing changes
        prev = t
        t = re.sub(r"\(\s*[:;,\s]*\)", "", t)  # emptied parentheses
        t = re.sub(r"\s*[:;,]\s*\)", ")", t)
        t = re.sub(r"\(\s*[:;,]\s*", "(", t)
        t = re.sub(r"\s{2,}", " ", t)
        t = re.sub(r"\s+([.,;:)])", r"\1", t)
    return t.strip()
_CAP = r"[A-Z][\w'&.\-]*"
_LINK = rf"(?:{_CAP}|of|and|&|the|de|la|for)"
CASE_NAME_RE = re.compile(rf"\b({_CAP}(?:\s+{_LINK}){{0,7}}?)\s+v\.?\s+({_CAP}(?:\s+{_LINK}){{0,7}})")
_LEADING = {"Under", "Section", "By", "In", "The", "See", "Per", "Applying", "As", "Following", "Unlike", "Also",
            "Both", "Neither", "Schedule", "Part"}
_WORD = r"(?:[A-Z][\w'’]*|\([A-Z][\w'’ ,]*\)|of|and|the|for)"
ACT_NAME_RE = re.compile(rf"\b({_WORD}(?:\s+{_WORD}){{0,9}}\s+(?:Act|Regulations)\s+(?:19|20)\d\d)\b")


def normalise(cite: str) -> str:
    c = cite.strip().strip("[]()").replace(" ", "").replace("¶", "p")
    c = re.sub(r"^([jlu])(?=\d)", lambda m: m.group(1).upper(), c)
    c = re.sub(r":([A-Za-z]{1,3})(?=\d)", lambda m: ":" + m.group(1).lower(), c)
    c = re.sub(r"^f(?=\d)", "F", c)
    return c


def resolve_passage(corpus: Corpus, jid: str, pid: str):
    """The passage for jid:pid, or the first part when pid names a whole section that was split."""
    j = corpus.get(jid)
    if not j:
        return None
    return j.passage(pid) or next((p for p in j.passages if p.pid.startswith(pid + ".")), None)


@dataclass
class CitationCheck:
    cite: str
    status: str  # valid | unknown_judgment | unknown_passage | unknown_fact | malformed | unknown_case_name
    kind: str  # judgment | fact | case_name

    @property
    def valid(self) -> bool:
        return self.status == "valid"


class CitationValidator:
    def __init__(self, corpus: Corpus, fact_sheet: FactSheet | None = None):
        self.corpus = corpus
        self.fact_sheet = fact_sheet
        self._own_title = (fact_sheet.title.lower() if fact_sheet else "")

    def check(self, cite: str) -> CitationCheck:
        c = normalise(cite)
        m = CITE_RE.match(c)
        if not m:
            return CitationCheck(c, "malformed", "judgment")
        jid, pid, fnum = m.groups()
        if fnum:
            ok = self.fact_sheet is not None and self.fact_sheet.paragraph(f"F{fnum}") is not None
            return CitationCheck(c, "valid" if ok else "unknown_fact", "fact")
        j = self.corpus.get(jid)
        if not j:
            return CitationCheck(c, "unknown_judgment", "judgment")
        if pid and not resolve_passage(self.corpus, jid, pid):
            return CitationCheck(c, "unknown_passage", "judgment")
        return CitationCheck(c, "valid", "judgment")

    def case_names(self, text: str) -> list[CitationCheck]:
        out = []
        for m in CASE_NAME_RE.finditer(text):
            name = f"{m.group(1)} v {m.group(2)}"
            if name.lower() in self._own_title or m.group(1).split()[-1].lower() in self._own_title:
                continue  # the client's own case
            found = self.corpus.find_by_name(name)
            out.append(CitationCheck(name, "valid" if found else "unknown_case_name", "case_name"))
        return out

    def unknown_acts(self, text: str) -> list[str]:
        """Statute names in the text that are not in the library (reported, not removed)."""
        unknown = []
        for m in ACT_NAME_RE.finditer(text):
            words = m.group(1).split()
            suffixes = [" ".join(words[i:]) for i in range(len(words) - 2)]
            if any(self.corpus.find_act(s) for s in suffixes):
                continue
            # Report the name without leading sentence words ("Under the ...", "and the ...").
            while len(words) > 3 and (words[0][0].islower() or words[0] in _LEADING or words[1] == "the"):
                words = words[1:]
            unknown.append(" ".join(words))
        return list(dict.fromkeys(unknown))

    def check_statement(self, st: CitedStatement) -> list[CitationCheck]:
        cites = list(st.citations) + [c for grp in INLINE_CITE_RE.findall(st.text) for c in re.split(r"[,;]", grp)]
        seen: dict[str, CitationCheck] = {}
        for c in cites:
            chk = self.check(c)
            seen.setdefault(chk.cite, chk)
        return list(seen.values()) + self.case_names(st.text)


@dataclass
class CitationReport:
    total: int = 0
    valid: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    statements: int = 0
    statements_with_valid_citation: int = 0
    judgment_citations: int = 0
    valid_judgment_citations: int = 0
    invalid_examples: list[str] = field(default_factory=list)
    cited_judgments: list[str] = field(default_factory=list)

    @property
    def existence_rate(self) -> float:
        return self.valid / self.total if self.total else 1.0

    @property
    def coverage(self) -> float:
        return self.statements_with_valid_citation / self.statements if self.statements else 0.0

    def as_dict(self) -> dict:
        return {
            "total_citations": self.total, "valid_citations": self.valid,
            "existence_rate": round(self.existence_rate, 4),
            "judgment_citations": self.judgment_citations,
            "valid_judgment_citations": self.valid_judgment_citations,
            "statements": self.statements,
            "statements_with_valid_citation": self.statements_with_valid_citation,
            "claim_coverage": round(self.coverage, 4),
            "by_status": self.by_status, "invalid_examples": self.invalid_examples[:10],
            "cited_judgments": self.cited_judgments,
        }


def audit_brief(brief: Brief, validator: CitationValidator) -> CitationReport:
    rep = CitationReport()
    status: Counter[str] = Counter()
    cited: list[str] = []
    for st in brief.statements():
        checks = validator.check_statement(st)
        rep.statements += 1
        if any(c.valid for c in checks):
            rep.statements_with_valid_citation += 1
        for c in checks:
            rep.total += 1
            status[c.status] += 1
            if c.valid:
                rep.valid += 1
            elif len(rep.invalid_examples) < 10:
                rep.invalid_examples.append(f"{c.cite} ({c.status})")
            if c.kind in ("judgment", "case_name"):
                rep.judgment_citations += 1
                rep.valid_judgment_citations += int(c.valid)
                jid = (c.cite.split(":")[0] if c.kind == "judgment"
                       else (validator.corpus.find_by_name(c.cite).id if c.valid else None))
                if c.valid and jid and jid not in cited:
                    cited.append(jid)
    rep.by_status = dict(status)
    rep.cited_judgments = cited
    return rep


def guard_brief(brief: Brief, validator: CitationValidator) -> tuple[Brief, list[str]]:
    """Remove citations that do not exist and drop claims left with no valid citation."""
    warnings: list[str] = []

    def clean(st: CitedStatement) -> CitedStatement | None:
        checks = validator.check_statement(st)
        bad_names = [c.cite for c in checks if c.kind == "case_name" and not c.valid]
        inline = [c.strip() for grp in INLINE_CITE_RE.findall(st.text) for c in re.split(r"[,;]", grp)]
        inline += BARE_ID_RE.findall(st.text)  # ids written loose in the prose: "(CRA s 22(3): L01:s22.1, facts F1)"
        good = [normalise(c) for c in [*st.citations, *inline] if validator.check(c).valid]
        bad = [c for c in [*st.citations, *inline] if not validator.check(c).valid]
        if bad:
            warnings.append(f"Removed non-existent citation(s) {bad} from: {st.text[:80]}")
        acts = validator.unknown_acts(st.text)
        if acts:
            warnings.append(f"Mentions legislation not in your library ({', '.join(acts)}); verify it independently: "
                            f"{st.text[:80]}")
        if bad_names:
            warnings.append(f"Dropped claim naming case(s) not in the corpus {bad_names}: {st.text[:80]}")
            return None
        if not good:
            warnings.append(f"Dropped uncited claim: {st.text[:80]}")
            return None
        text = strip_ids(st.text)
        return st.model_copy(update={"text": text, "citations": list(dict.fromkeys(good))})

    def clean_list(items: list[CitedStatement]) -> list[CitedStatement]:
        return [c for c in (clean(i) for i in items) if c is not None]

    out = brief.model_copy(deep=True)
    out.summary, out.facts, out.conclusion = clean_list(out.summary), clean_list(out.facts), clean_list(out.conclusion)
    out.remedies, out.time_limits, out.evidence = (clean_list(out.remedies), clean_list(out.time_limits),
                                                   clean_list(out.evidence))
    for issue in out.issues:
        for attr in ("supporting_precedents", "opposing_precedents"):
            kept = []
            for p in getattr(issue, attr):
                if validator.corpus.get(p.judgment_id) is None:
                    warnings.append(f"Removed precedent not in corpus: {p.judgment_id} {p.case_name}")
                    continue
                prop = clean(p.proposition)
                if prop is None:
                    prop = CitedStatement(text=p.proposition.text, citations=[p.judgment_id])
                p.proposition = prop
                j = validator.corpus.get(p.judgment_id)
                p.case_name, p.citation = j.name, j.citation
                kept.append(p)
            setattr(issue, attr, kept)
        issue.supporting_argument = clean_list(issue.supporting_argument)
        issue.opposing_argument = clean_list(issue.opposing_argument)
        assessed = clean(issue.assessment)
        issue.assessment = assessed or CitedStatement(
            text="No assessment could be supported by verified citations.", citations=[])
    out.warnings = list(dict.fromkeys([*out.warnings, *warnings]))
    return out, warnings


def render_citation(cite: str, corpus: Corpus) -> str:
    c = normalise(cite)
    m = CITE_RE.match(c)
    if not m:
        return c
    jid, pid, fnum = m.groups()
    if fnum:
        return f"Fact sheet ¶{fnum}"
    j = corpus.get(jid)
    if not j:
        return c
    if not pid:
        return j.cite()
    p = resolve_passage(corpus, jid, pid)
    if p and p.pid != pid:  # whole section cited: show "s 11", not "s 11 (part 1 of 3)"
        return j.cite().rstrip() + (", " if j.is_legislation else ", ") + re.sub(r"\s*\(part \d+ of \d+\)", "", p.display)
    return j.cite(pid)
