"""Render a compiled brief, the debate transcript and the issue list as Markdown."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from legal_brief.citations import render_citation
from legal_brief.corpus import Corpus
from legal_brief.models import Brief, CitedStatement

DISCLAIMER = ("Prepared by an AI research assistant for review by a qualified lawyer. It is not legal advice. "
              "Check every authority against the official source before relying on it.")


def _cites(st: CitedStatement, corpus: Corpus) -> str:
    if not st.citations:
        return ""
    return " — " + "; ".join(render_citation(c, corpus) for c in st.citations)


def _bullet(st: CitedStatement, corpus: Corpus) -> str:
    return f"- {st.text}{_cites(st, corpus)}"


def render_brief(brief: Brief, corpus: Corpus, *, mode: str = "offline", report: dict | None = None) -> str:
    out = [f"# Brief: {brief.title}", "",
           f"**Case** {brief.case_id} · **Acting for** {brief.acting_for} · **Prepared** {date.today():%d %B %Y} · "
           f"**Mode** {mode}", "", f"> {DISCLAIMER}", ""]
    out += ["## Summary", ""] + [_bullet(s, corpus) for s in brief.summary] + [""]
    out += ["## Issues", ""]
    for n, i in enumerate(brief.issues, 1):
        out += [f"{n}. **{i.issue_id}.** {i.question}"]
    out.append("")
    out += ["## Key facts", ""] + [_bullet(s, corpus) for s in brief.facts] + [""]
    for i in brief.issues:
        out += [f"## {i.issue_id}. {i.question}", ""]
        for label, entries in (("Supporting precedents", i.supporting_precedents),
                               ("Opposing precedents", i.opposing_precedents)):
            out += [f"**{label}**", ""]
            if not entries:
                out += ["- None retrieved.", ""]
                continue
            out += ["| Case | Proposition | Cite |", "|---|---|---|"]
            for e in entries:
                cite = "; ".join(render_citation(c, corpus) for c in e.proposition.citations)
                out.append(f"| *{e.case_name}* {e.citation} | {e.proposition.text.replace('|', '/')} | {cite} |")
            out.append("")
        out += ["**Argument for the client**", ""] + ([_bullet(s, corpus) for s in i.supporting_argument] or ["- None."]) + [""]
        out += ["**Argument for the other side**", ""] + ([_bullet(s, corpus) for s in i.opposing_argument] or ["- None."]) + [""]
        out += ["**Assessment**", "", _bullet(i.assessment, corpus), ""]
    out += ["## Conclusion", ""] + [_bullet(s, corpus) for s in brief.conclusion] + [""]

    cited: dict[str, set[str]] = {}
    for st in brief.statements():
        for c in st.citations:
            if c[:1] in "JLU" and c[1:2].isdigit():
                jid, _, pid = c.partition(":")
                cited.setdefault(jid, set()).add(pid)
    out += ["## Authorities cited", ""]
    for jid in sorted(cited):
        j = corpus.get(jid)
        if j:
            paras = ", ".join(f"¶{p[1:]}" for p in sorted(x for x in cited[jid] if x)) or "generally"
            out.append(f"- **{jid}** *{j.name}* {j.citation} ({j.court}) — {paras}")
    out.append("")
    if report:
        out += ["## Citation check", "",
                f"- {report['valid_citations']} of {report['total_citations']} citations resolve to the corpus or the fact "
                f"sheet ({report['existence_rate']:.0%}).",
                f"- {report['statements_with_valid_citation']} of {report['statements']} statements carry at least one "
                f"verified citation ({report['claim_coverage']:.0%}).", ""]
    if brief.warnings:
        out += ["## Warnings", ""] + [f"- {w}" for w in brief.warnings] + [""]
    return "\n".join(out)


def render_transcript(session) -> str:
    s, corpus = session, session.corpus
    out = [f"# Debate transcript: {s.fact_sheet.title}", "", f"Mode: {s.mode} · LLM calls: {s.llm_calls}", ""]
    for t in s.turns:
        who = "Argument Agent (client)" if t.speaker == "argument" else "Counter-Argument Agent (other side)"
        out += [f"## Round {t.round}: {who}", ""]
        for p in t.points:
            reply = f" *(replies to {p.responds_to})*" if p.responds_to else ""
            cites = "; ".join(render_citation(c, corpus) for c in p.citations)
            out.append(f"- **{p.point_id}** [{p.issue_id}]{reply} {p.text} — {cites}")
        out.append("")
    out += ["## Shared issue list: event log", "", "| # | Agent | Action | Issue | Detail |", "|---|---|---|---|---|"]
    for e in s.board.events:
        out.append(f"| {e.seq} | {e.author} | {e.action} | {e.issue_id or ''} | {e.detail.replace('|', '/')[:140]} |")
    return "\n".join(out) + "\n"


def write_case_outputs(result, out_dir: Path) -> dict[str, Path]:
    """Write brief.md, brief.json, raw_brief.json, issue_board.json, debate.md and trace.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    s, compiled = result.session, result.compiled
    paths = {
        "brief_md": out_dir / "brief.md", "brief_json": out_dir / "brief.json",
        "raw_brief_json": out_dir / "raw_brief.json", "issue_board": out_dir / "issue_board.json",
        "debate": out_dir / "debate.md", "trace": out_dir / "trace.json",
    }
    paths["brief_md"].write_text(render_brief(compiled.final, s.corpus, mode=s.mode, report=compiled.final_report),
                                 encoding="utf-8")
    paths["brief_json"].write_text(compiled.final.model_dump_json(indent=2), encoding="utf-8")
    paths["raw_brief_json"].write_text(compiled.raw.model_dump_json(indent=2), encoding="utf-8")
    paths["issue_board"].write_text(s.board.to_json(), encoding="utf-8")
    paths["debate"].write_text(render_transcript(s), encoding="utf-8")
    paths["trace"].write_text(json.dumps({
        "mode": s.mode, "llm_calls": s.llm_calls, "seconds": round(result.seconds, 3),
        "structured_facts": s.facts.model_dump() if s.facts else None,
        "citation_report_raw": compiled.raw_report, "citation_report_final": compiled.final_report,
        "warnings": s.warnings, "events": s.trace,
    }, indent=2), encoding="utf-8")
    return paths
