"""Command-line interface.

    python -m legal_brief brief data/fact_sheets/FS01_nair_v_brightwater.md
    python -m legal_brief eval
    python -m legal_brief search "advertisement offer reward deposit" --doctrine offer_acceptance
    python -m legal_brief corpus
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from legal_brief.config import PROVIDERS, Settings
from legal_brief.corpus import load_corpus
from legal_brief.llm import LLMUnavailable

console = Console()


def _settings(args) -> Settings:
    s = Settings.from_env()
    return s.with_overrides(provider=getattr(args, "provider", None), model=getattr(args, "model", None),
                            debate_rounds=getattr(args, "rounds", None), top_k=getattr(args, "top_k", None),
                            doctrine_boost=getattr(args, "boost", None),
                            output_dir=Path(args.out) if getattr(args, "out", None) else None)


def cmd_brief(args) -> int:
    from legal_brief.orchestration import run_case
    from legal_brief.render import write_case_outputs

    settings = _settings(args)
    path = Path(args.fact_sheet)
    if not path.exists():
        console.print(f"[red]Fact sheet not found:[/red] {path}")
        return 2
    with console.status(f"Running the debate ({settings.provider}) ..."):
        result = asyncio.run(run_case(path, settings))
    s, c = result.session, result.compiled
    out = write_case_outputs(result, settings.output_dir / s.fact_sheet.case_id)

    table = Table(title=f"Shared issue list: {s.fact_sheet.title}", show_lines=True)
    for col in ("Issue", "Question", "Supporting", "Opposing"):
        table.add_column(col)
    for i in s.board.issues:
        name = lambda jid: s.corpus.get(jid).name if s.corpus.get(jid) else jid  # noqa: E731
        table.add_row(i.id, i.question, "\n".join(name(j) for j in i.supporting) or "-",
                      "\n".join(name(j) for j in i.opposing) or "-")
    console.print(table)
    r = c.final_report
    console.print(f"Citations verified: [bold]{r['valid_citations']}/{r['total_citations']}[/bold] "
                  f"({r['existence_rate']:.0%}) · claims with a citation: {r['claim_coverage']:.0%} · "
                  f"mode {s.mode} · LLM calls {s.llm_calls} · {result.seconds:.2f}s")
    if args.show:
        console.print(Markdown(out["brief_md"].read_text(encoding="utf-8")))
    console.print("Wrote: " + ", ".join(str(p) for p in out.values()))
    for w in c.final.warnings[:5]:
        console.print(f"[yellow]warning:[/yellow] {w}")
    return 0


def cmd_eval(args) -> int:
    from legal_brief.evaluation import run_evaluation

    settings = _settings(args)
    only = [x.strip().upper() for x in args.only.split(",")] if args.only else None

    def progress(m):
        console.print(f"{m.case_id}: retrieval recall {m.retrieval_recall:.0%} · brief recall {m.brief_recall:.0%} · "
                      f"citations exist (raw) {m.citation_existence_raw:.0%} · {m.seconds:.2f}s")

    summary = asyncio.run(run_evaluation(settings, only=only, ablation=not args.no_ablation, progress=progress))
    table = Table(title=f"Evaluation ({summary['mode']}, {summary['fact_sheets']} fact sheets)")
    table.add_column("Metric")
    table.add_column("Macro avg", justify="right")
    from legal_brief.evaluation.runner import METRICS
    for key, label in METRICS:
        v = summary["macro"].get(key)
        table.add_row(label, "n/a" if v is None else f"{v:.1%}")
    console.print(table)
    console.print(f"Report: {settings.output_dir / 'eval' / 'report.md'}")
    return 0


def cmd_search(args) -> int:
    from legal_brief.retrieval import HybridRetriever

    settings = _settings(args)
    corpus = load_corpus(str(settings.corpus_path))
    hits = HybridRetriever(corpus, doctrine_boost=settings.doctrine_boost).search(args.query, top_k=args.k,
                                                                                   doctrine=args.doctrine)
    table = Table(title=f"Top {args.k} judgments for: {args.query}")
    for col in ("Rank", "Id", "Case", "Score", "Text score", "Best passage"):
        table.add_column(col)
    for n, h in enumerate(hits, 1):
        j = corpus.get(h.judgment_id)
        table.add_row(str(n), j.id, j.full_name, f"{h.score:.3f}", f"{h.text_score:.3f}",
                      corpus.passage(h.best_passage).text[:90] + "...")
    console.print(table)
    return 0


def cmd_corpus(args) -> int:
    settings = _settings(args)
    corpus = load_corpus(str(settings.corpus_path))
    table = Table(title=f"Judgment corpus ({len(corpus)} judgments, {len(corpus.passages)} passages)")
    for col in ("Id", "Case", "Court", "Doctrines"):
        table.add_column(col)
    for j in corpus.judgments:
        table.add_row(j.id, j.full_name, j.court, ", ".join(f"{k}:{v}" for k, v in j.doctrines.items()))
    console.print(table)
    return 0


def cmd_check(args) -> int:
    from legal_brief.llm import check_connection

    settings = _settings(args)
    console.print(f"Provider {settings.provider!r}, model {settings.model or '(default)'!r}: sending one small request ...")
    try:
        console.print("[green]OK[/green] " + asyncio.run(check_connection(settings)))
        return 0
    except LLMUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 - show the provider's error to the user
        console.print(f"[red]Request failed:[/red] {type(e).__name__}: {e}")
        return 4


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="legal-brief", description="Legal Case Precedent Briefing Assistant")
    p.add_argument("-v", "--verbose", action="store_true", help="log every agent step")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--provider", choices=PROVIDERS, help="LLM provider (default from LLM_PROVIDER, else offline)")
        sp.add_argument("--model", help="model or deployment name")
        sp.add_argument("--rounds", type=int, help="debate rounds (default 2)")
        sp.add_argument("--top-k", dest="top_k", type=int, help="precedents retrieved per issue (default 5)")
        sp.add_argument("--boost", type=float, help="doctrine metadata boost in retrieval (0 = text only)")
        sp.add_argument("--out", help="output directory (default ./outputs)")

    b = sub.add_parser("brief", help="generate a brief for one fact sheet")
    b.add_argument("fact_sheet")
    b.add_argument("--show", action="store_true", help="print the brief to the terminal")
    common(b)
    b.set_defaults(func=cmd_brief)

    e = sub.add_parser("eval", help="evaluate on the 8 fact sheets with known precedents")
    e.add_argument("--only", help="comma-separated case ids, e.g. FS01,FS04")
    e.add_argument("--no-ablation", action="store_true", help="skip the text-only retrieval ablation")
    common(e)
    e.set_defaults(func=cmd_eval)

    s = sub.add_parser("search", help="query the judgment corpus directly")
    s.add_argument("query")
    s.add_argument("--doctrine", help="doctrine key to boost")
    s.add_argument("-k", type=int, default=5)
    common(s)
    s.set_defaults(func=cmd_search)

    k = sub.add_parser("check", help="send one small request to confirm the LLM key and deployment work")
    common(k)
    k.set_defaults(func=cmd_check)

    c = sub.add_parser("corpus", help="list the judgment corpus")
    common(c)
    c.set_defaults(func=cmd_corpus)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    try:
        return args.func(args)
    except LLMUnavailable as e:
        console.print(f"[red]LLM provider not available:[/red] {e}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
