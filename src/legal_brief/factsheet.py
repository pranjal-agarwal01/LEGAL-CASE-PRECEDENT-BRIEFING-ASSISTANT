"""Load a markdown fact sheet and number its paragraphs (F1, F2, ...) for citation."""

from __future__ import annotations

import re
from pathlib import Path

from legal_brief.models import FactParagraph, FactSheet


def _sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"_head": []}
    current = "_head"
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*)", line)
        if m:
            current = m.group(1).strip().lower()
            sections[current] = []
        else:
            sections[current].append(line)
    return sections


def parse_fact_sheet(text: str, source_path: str = "") -> FactSheet:
    title_m = re.search(r"^#\s+(.*)$", text, re.M)
    heading = title_m.group(1).strip() if title_m else "Untitled matter"
    id_m = re.match(r"(?:fact sheet\s+)?(FS\d+)\s*[:\-]\s*(.*)", heading, re.I)
    if id_m:
        case_id, title = id_m.group(1).upper(), id_m.group(2).strip()
    else:
        case_id, title = (Path(source_path).stem.split("_")[0].upper() or "CASE"), heading
    acting_m = re.search(r"^acting for:\s*(.+)$", text, re.I | re.M)
    acting_for = acting_m.group(1).strip() if acting_m else "Claimant"
    juris_m = re.search(r"^jurisdiction:\s*(.+)$", text, re.I | re.M)
    area_m = re.search(r"^practice area:\s*(.+)$", text, re.I | re.M)
    area_text = area_m.group(1).lower() if area_m else ""
    practice_area = next((k for k, words in (("employment", "employ"), ("property", "landlord|tenan|property|housing"),
                                             ("contract", "contract|consumer"), ("tort", "tort|injur|negligen"))
                          if re.search(words, area_text)), "")

    secs = _sections(text)
    parties = [re.sub(r"^[-*]\s*", "", ln).strip() for key, lines in secs.items() if key.startswith("part")
               for ln in lines if ln.strip().startswith(("-", "*"))]

    facts: list[str] = []
    for key, lines in secs.items():
        if key.startswith(("fact", "chronolog", "background")):
            buf: list[str] = []
            for ln in lines:
                if re.match(r"^\s*\d+[.)]\s+", ln):
                    if buf:
                        facts.append(" ".join(buf))
                    buf = [re.sub(r"^\s*\d+[.)]\s+", "", ln).strip()]
                elif ln.strip() and buf:
                    buf.append(ln.strip())
                elif ln.strip():
                    buf = [ln.strip()]
            if buf:
                facts.append(" ".join(buf))

    objective = " ".join(
        ln.strip() for key, lines in secs.items() if "objective" in key or "instructions" in key for ln in lines if ln.strip()
    )

    paragraphs = [FactParagraph(ref=f"F{i}", kind="fact", text=t) for i, t in enumerate(facts, 1)]
    if objective:
        paragraphs.append(FactParagraph(ref=f"F{len(facts) + 1}", kind="objective", text=objective))
    if not paragraphs:  # free-text fact sheet: fall back to blank-line paragraphs
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip() and not b.strip().startswith("#")]
        paragraphs = [FactParagraph(ref=f"F{i}", text=" ".join(b.split())) for i, b in enumerate(blocks, 1)]

    return FactSheet(case_id=case_id, title=title, acting_for=acting_for, source_path=source_path,
                     practice_area=practice_area,
                     jurisdiction=juris_m.group(1).strip() if juris_m else "England and Wales",
                     raw_text=text, parties_block=parties, paragraphs=paragraphs)


def load_fact_sheet(path: Path | str) -> FactSheet:
    path = Path(path)
    return parse_fact_sheet(path.read_text(encoding="utf-8"), str(path))
