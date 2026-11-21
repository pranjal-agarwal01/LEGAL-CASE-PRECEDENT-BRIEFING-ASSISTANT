"""Turn uploaded documents into text, citable judgment paragraphs and matter facts.

* `extract_text` reads PDF, Word (.docx), HTML, Markdown and plain text.
* `split_judgment` finds the numbered paragraphs of a judgment ([1], 1., 12) ...), so a
  citation such as U4:p37 means paragraph 37 exactly as the court numbered it. Text
  without numbered paragraphs is split into parts of about 200 words (U4:c3 = part 3).
* `judgment_metadata` reads the case name, neutral citation, court and date, and tags
  the judgment with the doctrines it decides (LLM when configured, regex otherwise).
* `paragraphs_from_text` numbers free-text facts F1, F2 ... for a matter.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel

from legal_brief.doctrines import DOCTRINES

log = logging.getLogger(__name__)

MAX_PARA_WORDS = 380
CHUNK_WORDS = 200
ALLOWED = {".pdf", ".docx", ".txt", ".md", ".html", ".htm"}


class UnsupportedFile(ValueError):
    pass


# --------------------------------------------------------------------------- text extraction
def extract_text(filename: str, data: bytes) -> str:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED:
        raise UnsupportedFile(f"Unsupported file type {ext or '(none)'}; upload PDF, Word (.docx), HTML or text.")
    if ext == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in reader.pages]
        except Exception as e:  # noqa: BLE001 - corrupt or encrypted PDFs
            raise UnsupportedFile(f"Could not read this PDF ({type(e).__name__}).") from e
        text = "\n".join(_strip_page_furniture(pages))
        if len(text.strip()) < 200:
            raise UnsupportedFile("This PDF has no text layer (it may be a scan). Upload a text PDF or Word file.")
        return _normalise(text)
    if ext == ".docx":
        from docx import Document

        try:
            doc = Document(io.BytesIO(data))
        except Exception as e:  # noqa: BLE001
            raise UnsupportedFile(f"Could not read this Word file ({type(e).__name__}).") from e
        lines = []
        for para in doc.paragraphs:
            t = para.text.strip()
            num = _docx_number(para)
            lines.append(f"{num}. {t}" if num and t and not re.match(r"^\[?\d+[.\])]", t) else t)
        return _normalise("\n".join(lines))
    text = data.decode("utf-8", errors="replace")
    if ext in (".html", ".htm"):
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        import html as _html

        text = _html.unescape(text)
    return _normalise(text)


_docx_counters: dict[int, int] = {}


def _docx_number(para) -> int | None:
    """Word auto-numbered paragraphs lose their numbers in .text; rebuild a simple top-level count."""
    try:
        numpr = para._p.pPr.numPr if para._p.pPr is not None else None
    except AttributeError:
        numpr = None
    if numpr is None or numpr.ilvl is None or int(numpr.ilvl.val) != 0:
        return None
    key = int(numpr.numId.val)
    _docx_counters[key] = _docx_counters.get(key, 0) + 1
    return _docx_counters[key]


def _strip_page_furniture(pages: list[str]) -> list[str]:
    """Remove lines repeated at the top or bottom of most pages (running headers, page numbers)."""
    if len(pages) < 3:
        return pages
    from collections import Counter

    edges = Counter()
    for p in pages:
        ls = [ln.strip() for ln in p.splitlines() if ln.strip()]
        for ln in ls[:2] + ls[-2:]:
            edges[re.sub(r"\d+", "#", ln)] += 1
    common = {k for k, n in edges.items() if n >= max(3, len(pages) // 2)}
    out = []
    for p in pages:
        out.append("\n".join(ln for ln in p.splitlines()
                             if re.sub(r"\d+", "#", ln.strip()) not in common and not re.fullmatch(r"\s*\d+\s*", ln)))
    return out


def _normalise(text: str) -> str:
    text = text.replace("\r", "").replace(" ", " ").replace("\x0c", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # words hyphenated across lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- judgment paragraphs
@dataclass
class Para:
    pid: str
    label: str
    text: str


_NUM = re.compile(r"(?m)^\s*(?:\[(\d{1,4})\]|(\d{1,4})[.)])\s+(?=\S)")


def split_judgment(text: str) -> list[Para]:
    """Numbered paragraphs when the judgment has them (the usual case), else ~200-word parts."""
    marks = [(m.start(), m.end(), int(m.group(1) or m.group(2))) for m in _NUM.finditer(text)]
    seq, expected = [], 1
    for start, end, n in marks:  # keep the longest run that counts 1, 2, 3 ... in order
        if n == expected:
            seq.append((start, end, n))
            expected += 1
    covered = sum(len(text[s:]) for s, _, _ in seq[:1])
    if len(seq) >= 5 and covered > 0.5 * len(text):
        paras: list[Para] = []
        head = text[: seq[0][0]].strip()
        if head:
            paras.append(Para("p0", "heading", _squash(head)[:4000]))
        for k, (start, end, n) in enumerate(seq):
            stop = seq[k + 1][0] if k + 1 < len(seq) else len(text)
            body = _squash(text[end:stop])
            pieces = _split_words(body, MAX_PARA_WORDS)
            for i, piece in enumerate(pieces, 1):
                pid = f"p{n}" + (f".{i}" if len(pieces) > 1 else "")
                paras.append(Para(pid, f"¶{n}" + (f" (part {i})" if len(pieces) > 1 else ""), piece))
        return paras
    blocks = [_squash(b) for b in re.split(r"\n\s*\n", text) if b.strip()]
    chunks, cur = [], ""
    for b in blocks:
        for piece in _split_words(b, CHUNK_WORDS):
            if cur and len((cur + " " + piece).split()) > CHUNK_WORDS:
                chunks.append(cur)
                cur = piece
            else:
                cur = f"{cur} {piece}".strip()
    if cur:
        chunks.append(cur)
    return [Para(f"c{i}", f"part {i}", c) for i, c in enumerate(chunks, 1)]


def _squash(s: str) -> str:
    return re.sub(r"\s*\n\s*", " ", s).strip()


def _split_words(text: str, max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    sentences = re.split(r"(?<=[.;:])\s+", text)
    out, cur = [], ""
    for snt in sentences:
        if cur and len((cur + " " + snt).split()) > max_words:
            out.append(cur)
            cur = snt
        else:
            cur = f"{cur} {snt}".strip()
    if cur:
        out.append(cur)
    return out


# --------------------------------------------------------------------------- metadata
NEUTRAL = re.compile(r"\[(\d{4})\]\s+((?:UKSC|UKPC|UKHL|EWCA\s+(?:Civ|Crim)|EWHC|UKEAT|EAT|UKUT|UKFTT|EWFC|EWCOP)"
                     r"(?:\s+\d+(?:\s*\([A-Za-z ]+\))?|\s+\(\w+\)\s+\d+)?)")
INSC = re.compile(r"\b((?:19|20)\d\d)\s*INSC\s*(\d{1,5})\b")
SCR = re.compile(r"\[(\d{4})\]\s*\d+\s*S\.?\s?C\.?\s?R\.?\s*\d+")
COURTS = [("UKSC", "UK Supreme Court"), ("UKHL", "House of Lords"), ("UKPC", "Privy Council"),
          ("EWCA", "Court of Appeal"), ("EWHC", "High Court"), ("EAT", "Employment Appeal Tribunal"),
          ("UKUT", "Upper Tribunal"), ("UKFTT", "First-tier Tribunal")]


class _LLMTag(BaseModel):
    doctrine: str
    stance: str  # pro | contra | mixed: does the judgment find the doctrine satisfied / liability established?


class JudgmentMetaLLM(BaseModel):
    document_type: str  # judgment | legislation
    jurisdiction: str  # e.g. "England and Wales", "India", "Scotland"
    case_name: str
    neutral_citation: str
    court: str
    judgment_date: str  # ISO yyyy-mm-dd or ""
    area: str  # contract | tort | property | employment | other
    summary: str
    doctrines: list[_LLMTag]


class JudgmentMeta(BaseModel):
    document_type: str = "judgment"
    jurisdiction: str = "India"
    name: str
    citation: str = ""
    court: str = ""
    date: str = ""
    area: str = "other"
    summary: str = ""
    doctrines: dict[str, str] = {}


def regex_metadata(text: str, filename: str = "") -> JudgmentMeta:
    head = text[:6000]
    m = NEUTRAL.search(head)
    citation = re.sub(r"\s+", " ", f"[{m.group(1)}] {m.group(2)}").strip() if m else ""
    court = next((name for code, name in COURTS if code in citation), "")
    name_m = re.search(r"(?m)^\s*([A-Z][^\n]{2,120}?\s+v\.?\s+[^\n]{2,120}?)\s*$", head)
    name = re.sub(r"\s+", " ", name_m.group(1)).strip(" .") if name_m else re.sub(r"[_\-]+", " ", filename.rsplit(".", 1)[0])
    date_m = re.search(r"\b(\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|"
                       r"November|December) (?:19|20)\d\d)\b", head)
    date = ""
    if date_m:
        from datetime import datetime

        try:
            date = datetime.strptime(date_m.group(1), "%d %B %Y").date().isoformat()
        except ValueError:
            date = ""
    from legal_brief.doctrines import score_doctrines

    scores = score_doctrines(text[:40000])
    tags = {k: "mixed" for k, s in sorted(scores.items(), key=lambda kv: -kv[1])[:4] if s >= 2}
    from legal_brief.jurisdiction import detect_offline

    juris = "England and Wales" if citation else (detect_offline(head)[0] or "India")
    insc = INSC.search(head)
    if insc and not citation:  # Supreme Court of India: neutral citation, with the SCR report when printed
        scr = SCR.search(head)
        citation = f"{insc.group(1)} INSC {insc.group(2)}" + (f"; {scr.group(0)}" if scr else "")
        court, juris = "Supreme Court of India", "India"
    hc = re.search(r"(?im)high court (?:of judicature )?(?:of|at|for) (?:the state of )?([a-z][a-z &]+?)"
                   r"(?:\s+at\s+[a-z .]+)?\s*$", head)
    if hc and not court:
        court = "High Court of " + " ".join(w if w == "&" else w.capitalize() for w in hc.group(1).split())
    if re.search(r"(?i)\(\d{4}\)\s*\d+\s*SCC|\bAIR\s+\d{4}|Supreme Court of India|High Court of \w+ at", head):
        juris = "India"
    is_act = bool(re.search(r"(?im)^\s*(the\s+)?[A-Z][\w ,()'’-]{3,90}\b(Act|Regulations|Rules|Code|Ordinance)"
                            r",?\s+(\d{4})\b", head)) and not re.search(r"\bv\.?\s", head[:600])
    if is_act:
        title_m = re.search(r"(?im)^\s*((?:the\s+)?[A-Z][\w ,()'’-]{3,90}\b(?:Act|Regulations|Rules|Code|Ordinance),?"
                            r"\s+\d{4})", head)
        name = title_m.group(1).strip() if title_m else name
    return JudgmentMeta(document_type="legislation" if is_act else "judgment", jurisdiction=juris,
                        name=name[:200], citation=citation, court=court, date=date, doctrines=tags)


META_INSTRUCTIONS = (
    "You index documents for a law firm's legal research library. Say whether the document is a 'judgment' or "
    "'legislation' (an Act, regulations, a code or an ordinance), and the jurisdiction whose law it is (for "
    "example 'England and Wales', 'Scotland', 'India', 'Ireland', 'New York, United States'). For legislation, "
    "put its short title (e.g. 'Specific Relief Act, 1963') in case_name and leave neutral_citation empty. For a "
    "judgment, from its opening and closing text return: the short case name as lawyers cite it (e.g. 'Smith v "
    "Jones Ltd'); the "
    "neutral citation exactly as printed (e.g. '[2023] EWCA Civ 1023') or '' if none; the court; the judgment date "
    "as yyyy-mm-dd or ''; the area of law (contract, tort, property, employment or other); a neutral 2-3 sentence "
    "summary of what was decided and why; and the doctrines it decides, using ONLY keys from this list, each with "
    "stance 'pro' (the court found the doctrine satisfied / liability or the right established), 'contra' (it "
    "found it not satisfied) or 'mixed'. Keys: " + ", ".join(DOCTRINES) + ". Do not guess facts you cannot see."
)


async def judgment_metadata(text: str, filename: str, client=None) -> JudgmentMeta:
    base = regex_metadata(text, filename)
    if client is None:
        return base
    from agent_framework import Agent

    from legal_brief.llm import run_structured

    excerpt = text[:9000] + ("\n...\n" + text[-3500:] if len(text) > 12500 else "")
    try:
        agent = Agent(client, META_INSTRUCTIONS, name="library_indexer")
        out = await run_structured(agent, excerpt, JudgmentMetaLLM, max_tokens=1500)
    except Exception as e:  # noqa: BLE001 - fall back to what the regexes found
        log.warning("judgment metadata via LLM failed: %s", e)
        return base
    tags = {t.doctrine: (t.stance if t.stance in ("pro", "contra", "mixed") else "mixed")
            for t in out.doctrines if t.doctrine in DOCTRINES}
    from legal_brief.jurisdiction import normalise

    return JudgmentMeta(
        document_type="legislation" if out.document_type.lower().startswith("legis") else "judgment",
        jurisdiction=normalise(out.jurisdiction or base.jurisdiction),
        name=(out.case_name or base.name)[:200], citation=out.neutral_citation or base.citation,
        court=out.court or base.court, date=out.judgment_date if re.fullmatch(r"\d{4}-\d\d-\d\d", out.judgment_date or "") else base.date,
        area=out.area if out.area in ("contract", "tort", "property", "employment") else "other",
        summary=out.summary.strip()[:1200], doctrines=tags or base.doctrines,
    )


# --------------------------------------------------------------------------- legislation
_ENACTING = re.compile(r"\b(BE it enacted|It is hereby enacted|WHEREAS it is expedient)\b", re.I)
_SECTION = re.compile(r"(?m)^\s*\[?(\d{1,4})([A-Z]{0,3})\.\s*(?=\S)")
_FOOTNOTE = re.compile(
    r"(?m)^\s*\d+\.\s*(?:Subs\.|Ins\.|Omitted|Rep\.|Added|The words|The figures|Certain words|For the words|Vide|"
    r"Renumbered|Now see|Came into force|w\.e\.f\.|"
    r"Extended to|This Act has been|The Act has been).*$")
_SCHEDULE = re.compile(r"(?m)^\s*THE\s+(?:FIRST\s+|SECOND\s+|THIRD\s+|FOURTH\s+)?SCHEDULE\b\.?")


def _repair_glyphs(text: str) -> str:
    """PDFs often lose dashes and quotes as U+FFFD; restore the usual reading."""
    text = re.sub(r"(?<=[.\w)])�(?=[(\w\s])", "—", text)  # "title.�(1)" -> "title.—(1)"
    return text.replace("�", "”")


def _numbered_run(text: str) -> list[tuple[int, int, str]]:
    """(start, end, number) of numbered headings that run 1, 2, 3 ... allowing inserted sections (5A) and
    small gaps where sections were omitted."""
    out: list[tuple[int, int, str]] = []
    last = 0
    for m in _SECTION.finditer(text):
        n, suffix = int(m.group(1)), m.group(2)
        if (not out and n == 1) or (out and ((n == last and suffix) or last < n <= last + 3)):
            out.append((m.start(), m.end(), f"{n}{suffix}"))
            last = n
    return out


def split_legislation(text: str) -> list[Para]:
    """Sections (s 5, s 5A) and schedule entries (Sch, art 65) of an Act, skipping the table of contents
    that official prints place before the enacting formula, and the amendment footnotes on each page."""
    text = _repair_glyphs(text)
    found = list(_ENACTING.finditer(text))
    body_start = found[-1].start() if found else 0
    body = _FOOTNOTE.sub("", text[body_start:])
    sched = _SCHEDULE.search(body, pos=max(0, len(body) // 3))  # schedules follow the sections
    sections_text, schedule_text = (body[:sched.start()], body[sched.start():]) if sched else (body, "")
    paras: list[Para] = []
    run = _numbered_run(sections_text)
    if len(run) < 3:  # not a recognisable Act: fall back to paragraphs
        return split_judgment(text)
    preamble = _squash(sections_text[: run[0][0]])
    if preamble:
        paras.append(Para("s0", "preamble", preamble[:3000]))
    for k, (start, end, num) in enumerate(run):
        stop = run[k + 1][0] if k + 1 < len(run) else len(sections_text)
        body_text = _squash(sections_text[end:stop])
        pieces = _split_words(body_text, MAX_PARA_WORDS)
        for i, piece in enumerate(pieces, 1):
            pid = f"s{num}" + (f".{i}" if len(pieces) > 1 else "")
            paras.append(Para(pid, f"s {num}" + (f" (part {i})" if len(pieces) > 1 else ""), piece))
    if schedule_text:
        arts = _numbered_run(schedule_text)
        if len(arts) >= 3:
            head = _squash(schedule_text[: arts[0][0]])
            if head:
                paras.append(Para("sch0", "Schedule", head[:2000]))
            for k, (start, end, num) in enumerate(arts):
                stop = arts[k + 1][0] if k + 1 < len(arts) else len(schedule_text)
                pieces = _split_words(_squash(schedule_text[end:stop]), MAX_PARA_WORDS)
                for i, piece in enumerate(pieces, 1):
                    pid = f"art{num}" + (f".{i}" if len(pieces) > 1 else "")
                    paras.append(Para(pid, f"Sch, art {num}" + (f" (part {i})" if len(pieces) > 1 else ""), piece))
        else:
            for i, piece in enumerate(_split_words(_squash(schedule_text), CHUNK_WORDS), 1):
                paras.append(Para(f"sch{i}", f"Schedule (part {i})", piece))
    return paras


def as_sections(paras: list[Para]) -> list[Para]:
    """Relabel numbered paragraphs of legislation as sections: p5 -> s5, '¶5' -> 's 5'."""
    out = []
    for p in paras:
        m = re.match(r"p(\d+)(\.\d+)?$", p.pid)
        if m:
            out.append(Para(f"s{m.group(1)}{m.group(2) or ''}", p.label.replace("¶", "s "), p.text))
        elif p.pid == "p0":
            out.append(Para("s0", "preamble", p.text))
        else:
            out.append(p)
    return out


# --------------------------------------------------------------------------- matter facts
def paragraphs_from_text(text: str, max_words: int = 90) -> list[str]:
    """Numbered facts: keep the user's own numbering or blank-line paragraphs; split long ones by sentence."""
    text = _normalise(text)
    numbered = [m for m in _NUM.finditer(text)]
    if len(numbered) >= 2:
        parts = []
        for k, m in enumerate(numbered):
            stop = numbered[k + 1].start() if k + 1 < len(numbered) else len(text)
            parts.append(_squash(text[m.end():stop]))
        lead = text[: numbered[0].start()].strip()
        blocks = ([_squash(lead)] if lead else []) + parts
    else:
        blocks = [_squash(b) for b in re.split(r"\n\s*\n|\n(?=[-*•]\s)", text) if b.strip()]
    out = []
    for b in blocks:
        b = re.sub(r"^[-*•]\s*", "", b)
        if len(b.split()) <= max_words:
            out.append(b)
            continue
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", b)
        cur = ""
        for snt in sentences:
            if cur and len((cur + " " + snt).split()) > max_words * 0.6:
                out.append(cur)
                cur = snt
            else:
                cur = f"{cur} {snt}".strip()
        if cur:
            out.append(cur)
    return [p for p in out if p]
