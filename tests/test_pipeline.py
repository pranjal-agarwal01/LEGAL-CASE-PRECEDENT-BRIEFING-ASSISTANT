"""End-to-end tests of the debate workflow (offline mode) and the evaluation harness, on Indian matters."""

import asyncio
import json

import pytest

from legal_brief.evaluation import run_evaluation, score_case
from legal_brief.orchestration import run_case
from legal_brief.render import render_brief, write_case_outputs

GOLD = {"FS01": ["J240778", "J240533"], "FS03": ["J230429", "J190159"], "FS04": ["J240770", "J240377"]}
FILES = {"FS01": "FS01_reddy_v_srinivasulu.md", "FS03": "FS03_sharma_v_traders.md", "FS04": "FS04_kaur_v_dhillon.md"}


@pytest.mark.parametrize("case_id", sorted(GOLD))
def test_debate_produces_fully_cited_brief(case_id, settings, fs_dir, tmp_path):
    result = asyncio.run(run_case(fs_dir / FILES[case_id], settings))
    s, brief = result.session, result.brief

    path = next(e for e in s.trace if e["action"] == "path")["detail"]
    assert path.startswith("fact_extractor -> precedent_retrieval -> argument")
    assert path.endswith("counter:round2 -> brief_compiler")

    # every agent wrote to the shared issue list
    authors = {e.author for e in s.board.events}
    assert {"fact_extractor", "precedent_retrieval", "argument", "counter_argument", "brief_compiler"} <= authors

    # both sides of the debate are present for every issue
    assert brief.issues and all(i.supporting_argument and i.opposing_argument for i in brief.issues)
    rebuttals = [p for t in s.turns if t.round == 2 for p in t.points if p.responds_to]
    assert rebuttals, "round 2 should answer the other side's points"

    rep = result.compiled.final_report
    assert rep["existence_rate"] == 1.0 and rep["claim_coverage"] == 1.0
    m = score_case(result, GOLD[case_id])
    assert m.retrieval_recall == 1.0 and m.brief_recall == 1.0

    md = render_brief(brief, s.corpus, report=rep)
    assert "## Authorities cited" in md and "Fact sheet ¶" in md and "INSC" in md
    paths = write_case_outputs(result, tmp_path / case_id)
    assert json.loads(paths["issue_board"].read_text(encoding="utf-8"))["events"]


def test_one_round_debate(settings, fs_dir):
    result = asyncio.run(run_case(fs_dir / "FS02_singh_v_mahto.md", settings.with_overrides(debate_rounds=1)))
    issues = result.session.board.issues
    assert {i.doctrine for i in issues} >= {"adverse_possession", "revenue_entries"}
    assert len(result.session.turns) == 2  # one round: argument + counter


def test_evaluation_harness(settings, tmp_path):
    summary = asyncio.run(run_evaluation(settings, out_dir=tmp_path, only=["FS02", "FS05"]))
    assert summary["fact_sheets"] == 2
    assert summary["macro"]["brief_recall"] == 1.0
    assert (tmp_path / "report.md").exists() and (tmp_path / "FS05" / "brief.md").exists()
