"""Run the system over the evaluation fact sheets and write a report."""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

from legal_brief.config import Settings
from legal_brief.evaluation.metrics import CaseMetrics, score_case
from legal_brief.factsheet import load_fact_sheet
from legal_brief.orchestration import run_case
from legal_brief.render import write_case_outputs

METRICS = [
    ("retrieval_recall", "Precedent recall: retrieval (issue list)"),
    ("retrieval_recall_text_only", "Precedent recall: retrieval, text only (no doctrine boost)"),
    ("brief_recall", "Precedent recall: final brief"),
    ("citation_existence_raw", "Citations that exist in corpus: raw compiler output"),
    ("judgment_citation_existence_raw", "Case-law citations that exist: raw compiler output"),
    ("citation_existence_final", "Citations that exist in corpus: final brief"),
    ("claim_coverage", "Claims carrying a verified citation"),
    ("gold_precision", "Cited judgments that are on the gold list"),
]


async def run_evaluation(settings: Settings, out_dir: Path | None = None, only: list[str] | None = None,
                         ablation: bool = True, client=None, progress=None) -> dict:
    gold_all = json.loads(settings.gold_path.read_text(encoding="utf-8"))["fact_sheets"]
    out_dir = out_dir or settings.output_dir / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[CaseMetrics] = []
    for case_id, g in gold_all.items():
        if only and case_id not in only:
            continue
        fs = load_fact_sheet(settings.fact_sheet_dir / g["file"])
        result = await run_case(fs, settings, client=client)
        m = score_case(result, g["relevant"])
        if ablation:  # same pipeline, retrieval without the doctrine metadata boost
            text_only = await run_case(fs, settings.with_overrides(provider="offline", doctrine_boost=0.0))
            m.retrieval_recall_text_only = score_case(text_only, g["relevant"]).retrieval_recall
        write_case_outputs(result, out_dir / case_id)
        rows.append(m)
        if progress:
            progress(m)

    def mean(key: str) -> float | None:
        vals = [getattr(r, key) for r in rows if getattr(r, key) is not None]
        return round(statistics.mean(vals), 4) if vals else None

    gold_total = sum(len(r.gold) for r in rows)
    summary = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "mode": settings.provider if settings.uses_llm else "offline",
        "model": settings.model or None,
        "settings": {"debate_rounds": settings.debate_rounds, "top_k": settings.top_k,
                     "doctrine_boost": settings.doctrine_boost},
        "fact_sheets": len(rows),
        "macro": {k: mean(k) for k, _ in METRICS},
        "micro": {
            "retrieval_recall": round(sum(len(set(r.gold) & set(r.retrieved)) for r in rows) / gold_total, 4) if gold_total else None,
            "brief_recall": round(sum(len(set(r.gold) & set(r.cited)) for r in rows) / gold_total, 4) if gold_total else None,
            "citations_raw": sum(r.citations_raw for r in rows),
            "citations_final": sum(r.citations_final for r in rows),
        },
        "cases": [r.as_dict() for r in rows],
    }
    (out_dir / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def render_report(summary: dict) -> str:
    m = summary["macro"]
    out = [
        "# Evaluation report: Legal Case Precedent Briefing Assistant", "",
        f"Generated {summary['generated']} · mode **{summary['mode']}**"
        + (f" (model `{summary['model']}`)" if summary.get("model") else "")
        + f" · {summary['fact_sheets']} fact sheets · debate rounds {summary['settings']['debate_rounds']} · "
          f"top-k {summary['settings']['top_k']} · doctrine boost {summary['settings']['doctrine_boost']}", "",
        "## Headline metrics (macro average over fact sheets)", "",
        "| Metric | Value |", "|---|---|",
    ]
    out += [f"| {label} | {_pct(m.get(k))} |" for k, label in METRICS]
    mi = summary["micro"]
    out += ["", f"Micro-averaged precedent recall: retrieval {_pct(mi['retrieval_recall'])}, brief {_pct(mi['brief_recall'])}. "
                f"Citations checked: {mi['citations_raw']} raw, {mi['citations_final']} final.", "",
            "## Per fact sheet", "",
            "| Case | Gold precedents | Retrieved | Cited in brief | Recall (retrieval) | Recall (text only) | Recall (brief) | Citations exist (raw) | Claim coverage | Missed | LLM fallbacks |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in summary["cases"]:
        fb = c.get("llm_fallbacks", 0)
        fb_txt = ("all (content filter)" if c.get("content_filtered") else str(fb)) if fb else "0"
        out.append(f"| {c['case_id']} | {', '.join(c['gold'])} | {len(c['retrieved'])} | {len(c['cited'])} | "
                   f"{_pct(c['retrieval_recall'])} | {_pct(c['retrieval_recall_text_only'])} | {_pct(c['brief_recall'])} | "
                   f"{_pct(c['citation_existence_raw'])} ({c['citations_raw']}) | {_pct(c['claim_coverage'])} | "
                   f"{', '.join(c['missed']) or '-'} | {fb_txt} |")
    if summary["mode"] != "offline" and any(c.get("llm_fallbacks") for c in summary["cases"]):
        out += ["", "Cases with LLM fallbacks were (partly) answered by the offline baseline; read their numbers with that in mind."]
    out += ["", "## How to read this", "",
            "- **Precedent recall** = known relevant precedents found ÷ known relevant precedents (gold list in `data/eval/gold.json`).",
            "- **Retrieval, text only** reruns retrieval with the doctrine-metadata boost switched off, isolating the hybrid BM25 + LSA search.",
            "- **Citations that exist** = citations resolving to a real judgment passage in `data/corpus/judgments.json` or a real fact-sheet paragraph, "
            "÷ all citations (free-text case names included). *Raw* is the compiler's output before the citation guard; the guard then removes anything unverifiable.",
            "- In offline mode the agents can only cite passages they retrieved, so raw citation existence is 100% by construction. "
            "With an LLM provider the same metric measures hallucinated citations.",
            "- Briefs, debate transcripts and the shared issue list for each case are in this folder under the case id.", ""]
    return "\n".join(out)
