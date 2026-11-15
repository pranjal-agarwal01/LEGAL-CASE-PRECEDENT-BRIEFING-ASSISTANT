from legal_brief.citations import CitationValidator, audit_brief, guard_brief
from legal_brief.factsheet import load_fact_sheet
from legal_brief.models import Brief, CitedStatement, IssueAnalysis


def _validator(corpus, fs_dir):
    return CitationValidator(corpus, load_fact_sheet(fs_dir / "FS03_hughes_v_peakfit.md"))


def test_citation_ids(corpus, fs_dir):
    v = _validator(corpus, fs_dir)
    assert v.check("J23:p2").valid
    assert v.check("[j23:P2]").valid  # normalised
    assert v.check("J23").valid
    assert v.check("J23:p9").status == "unknown_passage"
    assert v.check("J99:p1").status == "unknown_judgment"
    assert v.check("F3").valid and v.check("F42").status == "unknown_fact"
    assert v.check("Carlill 1893").status == "malformed"


def test_case_names_in_text(corpus, fs_dir):
    v = _validator(corpus, fs_dir)
    ok = v.case_names("As in Pharmaceutical Society of Great Britain v Boots Cash Chemists, display is not an offer.")
    assert [c.valid for c in ok] == [True]
    bad = v.case_names("See also Jenkins v Marlowe Holdings for the same point.")
    assert [c.status for c in bad] == ["unknown_case_name"]
    assert v.case_names("Hughes v PeakFit Ltd is the client's own case.") == []


def test_guard_removes_hallucinated_citations(corpus, fs_dir):
    v = _validator(corpus, fs_dir)
    brief = Brief(
        case_id="FS03", title="Hughes v PeakFit Ltd", acting_for="Claimant",
        summary=[CitedStatement(text="The advert was an offer.", citations=["J23:p2", "J99:p4"]),
                 CitedStatement(text="Jenkins v Marlowe Holdings decides this.", citations=["J23:p3"]),
                 CitedStatement(text="An uncited assertion.", citations=[])],
        issues=[IssueAnalysis(issue_id="I1", question="Offer?",
                              assessment=CitedStatement(text="Favourable [J23:p3].", citations=["F1"]))],
    )
    raw = audit_brief(brief, v)
    assert raw.total == 6 and raw.valid == 4  # J99:p4 and the invented case name do not exist
    final, warnings = guard_brief(brief, v)
    assert [s.citations for s in final.summary] == [["J23:p2"]]
    assert final.issues[0].assessment.text == "Favourable."
    assert final.issues[0].assessment.citations == ["F1", "J23:p3"]  # inline citation kept as structured
    rep = audit_brief(final, v)
    assert rep.existence_rate == 1.0 and rep.coverage == 1.0
    assert len(warnings) == 3
