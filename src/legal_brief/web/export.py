"""Export a finished brief to Word (.docx) and Markdown from the stored run payload."""

from __future__ import annotations

import io
import re
from datetime import datetime

DISCLAIMER = ("Prepared by an AI research assistant for review by a qualified lawyer. It is not legal advice. "
              "Check every authority against the official source before relying on it.")
SUPPORT_LABEL = {"supported": "Verified against source", "partial": "Partly supported by source",
                 "unsupported": "NOT supported by the cited source", "facts_only": "Facts", "unchecked": "Not checked"}


def cite_text(cite: str, auths: dict) -> str:
    if re.fullmatch(r"F\d+", cite):
        return f"Facts ¶{cite[1:]}"
    jid, _, pid = cite.partition(":")
    a = auths.get(jid)
    if not a:
        return cite
    p = (a.get("passages") or {}).get(pid) if pid else None
    where = (p or {}).get("label", "")
    if a["kind"] == "legislation":
        return f"{a['name']}" + (f", {where}" if where else "")
    return f"{a['name']} {a.get('citation', '')}".strip() + (f", {where}" if where else "")


def _statements(brief: dict):
    yield from brief.get("summary", [])
    yield from brief.get("facts", [])
    for i in brief.get("issues", []):
        for e in i.get("supporting_precedents", []) + i.get("opposing_precedents", []):
            yield e["proposition"]
        yield from i.get("supporting_argument", []) + i.get("opposing_argument", []) + [i["assessment"]]
    yield from brief.get("conclusion", [])


def to_markdown(matter: dict, result: dict) -> str:
    b, auths = result["brief"], result.get("authorities", {})

    def line(st):
        flag = " ⚠ *not supported by the cited source*" if st.get("support") == "unsupported" else ""
        cites = "; ".join(cite_text(c, auths) for c in st.get("citations", []))
        return f"- {st['text']}{' — ' + cites if cites else ''}{flag}"

    out = [f"# {matter['title']}", "", f"Acting for {matter['client_name']} ({matter['client_role']}) · "
           f"prepared {datetime.now():%d %B %Y}", "", f"> {DISCLAIMER}", "", "## Summary", ""]
    out += [line(s) for s in b.get("summary", [])] + ["", "## Key facts", ""] + [line(s) for s in b.get("facts", [])]
    for i in b.get("issues", []):
        out += ["", f"## {i['issue_id']}. {i['question']}", ""]
        if i.get("coverage") in ("none", "weak"):
            out += [f"> Library coverage: **{i['coverage']}**. {i.get('coverage_note', '')}", ""]
        for label, key in (("Supporting authorities", "supporting_precedents"),
                           ("Opposing authorities", "opposing_precedents")):
            out += [f"**{label}**", ""]
            out += [line({**e["proposition"], "text": f"{e['case_name']} {e['citation']}: {e['proposition']['text']}"})
                    for e in i.get(key, [])] or ["- None."]
            out.append("")
        out += ["**For the client**", ""] + ([line(s) for s in i.get("supporting_argument", [])] or ["- None."])
        out += ["", "**For the other side**", ""] + ([line(s) for s in i.get("opposing_argument", [])] or ["- None."])
        out += ["", "**Assessment**", "", line(i["assessment"])]
    out += ["", "## Conclusion", ""] + [line(s) for s in b.get("conclusion", [])]
    return "\n".join(out) + "\n"


def to_docx(matter: dict, result: dict) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    b, auths = result["brief"], result.get("authorities", {})
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Georgia", Pt(10.5)

    title = doc.add_heading(matter["title"], level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    meta = doc.add_paragraph()
    meta.add_run(f"Acting for {matter['client_name']} ({matter['client_role']})").bold = True
    if matter.get("opponent"):
        meta.add_run(f" · against {matter['opponent']}")
    meta.add_run(f" · prepared {datetime.now():%d %B %Y}")
    d = doc.add_paragraph()
    r = d.add_run(DISCLAIMER)
    r.italic, r.font.size, r.font.color.rgb = True, Pt(9), RGBColor(0x55, 0x55, 0x55)

    def bullet(stmt: dict, prefix: str = ""):
        p = doc.add_paragraph(style="List Bullet")
        if prefix:
            p.add_run(prefix).bold = True
        p.add_run(stmt["text"])
        cites = "; ".join(cite_text(c, auths) for c in stmt.get("citations", []))
        if cites:
            c = p.add_run(f" [{cites}]")
            c.font.size, c.font.color.rgb = Pt(9), RGBColor(0x44, 0x44, 0x66)
        if stmt.get("support") == "unsupported":
            w = p.add_run(" — not supported by the cited source; verify before use.")
            w.bold, w.font.color.rgb = True, RGBColor(0xA0, 0x20, 0x20)
        elif stmt.get("support") == "partial":
            w = p.add_run(" — partly supported.")
            w.font.size, w.font.color.rgb = Pt(9), RGBColor(0x8A, 0x60, 0x10)

    doc.add_heading("Summary", level=1)
    for s in b.get("summary", []):
        bullet(s)
    doc.add_heading("Key facts", level=1)
    for s in b.get("facts", []):
        bullet(s)
    for i in b.get("issues", []):
        doc.add_heading(f"{i['issue_id']}. {i['question']}", level=1)
        if i.get("coverage") in ("none", "weak"):
            p = doc.add_paragraph()
            r = p.add_run(f"Library coverage: {i['coverage']}. {i.get('coverage_note', '')}")
            r.bold, r.font.color.rgb = True, RGBColor(0xA0, 0x20, 0x20) if i["coverage"] == "none" else RGBColor(0x8A, 0x60, 0x10)
        for label, key in (("Supporting authorities", "supporting_precedents"),
                           ("Opposing authorities", "opposing_precedents")):
            doc.add_heading(label, level=2)
            entries = i.get(key, [])
            if not entries:
                doc.add_paragraph("None found in the library.")
            for e in entries:
                bullet(e["proposition"], prefix=f"{e['case_name']} {e['citation']}".strip() + ": ")
        doc.add_heading("Argument for the client", level=2)
        for s in i.get("supporting_argument", []) or [{"text": "None.", "citations": []}]:
            bullet(s)
        doc.add_heading("Argument for the other side", level=2)
        for s in i.get("opposing_argument", []) or [{"text": "None.", "citations": []}]:
            bullet(s)
        doc.add_heading("Assessment", level=2)
        bullet(i["assessment"])
    doc.add_heading("Conclusion", level=1)
    for s in b.get("conclusion", []):
        bullet(s)

    doc.add_heading("Authorities cited", level=1)
    used = sorted({c.split(":")[0] for s in _statements(b) for c in s.get("citations", []) if c[:1] in "JLU"})
    for jid in used:
        a = auths.get(jid)
        if not a:
            continue
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(f"{a['name']} {a.get('citation', '')}".strip()).bold = True
        kind = {"legislation": "Legislation", "judgment": "Judgment (uploaded by your firm)",
                "summary": "Case summary (paraphrased teaching summary, not the law report)"}.get(a["kind"], a["kind"])
        p.add_run(f" — {kind}" + (f". {a['url']}" if a.get("url") else ""))
    doc.add_paragraph().add_run(
        "Legislation: contains public sector information licensed under the Open Government Licence v3.0."
    ).font.size = Pt(8)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
