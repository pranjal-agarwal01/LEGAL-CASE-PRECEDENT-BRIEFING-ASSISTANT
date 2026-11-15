"""End-to-end tests of the debate workflow (offline mode) and the evaluation harness."""

import asyncio
import json

import pytest

from legal_brief.evaluation import run_evaluation, score_case
from legal_brief.orchestration import run_case
from legal_brief.render import render_brief, write_case_outputs

GOLD = {"FS01": ["J01", "J10", "J08"], "FS04": ["J37", "J38", "J36", "J39"], "FS06": ["J42", "J43", "J41", "J40"]}
FILES = {"FS01": "FS01_nair_v_brightwater.md", "FS04": "FS04_rowe_v_skyline.md", "FS06": "FS06_adeyemi_v_harbourside.md"}


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
    assert "## Authorities cited" in md and "Fact sheet ¶" in md
    paths = write_case_outputs(result, tmp_path / case_id)
    assert json.loads(paths["issue_board"].read_text(encoding="utf-8"))["events"]


def test_counter_argument_raises_defence_issue(settings, fs_dir):
    result = asyncio.run(run_case(fs_dir / "FS02_okafor_v_st_aldhelms.md", settings.with_overrides(debate_rounds=1)))
    issues = result.session.board.issues
    assert {i.doctrine for i in issues} >= {"informed_consent", "medical_standard"}
    assert len(result.session.turns) == 2  # one round: argument + counter


def test_evaluation_harness(settings, tmp_path):
    summary = asyncio.run(run_evaluation(settings, out_dir=tmp_path, only=["FS03", "FS07"]))
    assert summary["fact_sheets"] == 2
    assert summary["macro"]["brief_recall"] == 1.0
    assert (tmp_path / "report.md").exists() and (tmp_path / "FS03" / "brief.md").exists()
