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


def test_quote_fallback_uses_a_real_sentence(corpus):
    from legal_brief.verification import _best_sentence

    pairs = [(p.ref, p.text) for p in corpus.get("J37").passages]
    # a paraphrase of the passage: the real sentence is chosen, copied verbatim from the source
    ref, sentence = _best_sentence(pairs, "a contract is frustrated when an event destroys the state of affairs "
                                          "both parties treated as the basis of the contract")
    assert ref.startswith("J37:") and sentence in corpus.passage(ref).text
    # an unrelated claim finds no sentence, so no quote is shown
    assert _best_sentence(pairs, "the employer failed to pay the national minimum wage") is None


def test_ids_in_prose_become_readable(corpus):
    import re
    from pathlib import Path

    from legal_brief.citations import render_citation, strip_ids
    from legal_brief.config import PROJECT_ROOT
    from legal_brief.corpus import Corpus

    laws = Corpus.load_legislation(PROJECT_ROOT / "data" / "library" / "legislation.json")
    lab = lambda c: re.sub(r"\s*\(part \d+ of \d+\)", "", render_citation(c, laws).replace("*", ""))  # noqa: E731
    assert strip_ids("Right to reject within 30 days (CRA 2015 s 22(3): L01:s22.1, facts F1).", lab) == \
        "Right to reject within 30 days (CRA 2015 s 22(3))."
    assert strip_ids("The deadline is 1 June 2026 (calculate from F4 and L27:s111.1).", lab) == \
        "The deadline is 1 June 2026 (calculate from fact ¶4 and Employment Rights Act 1996, s 111)."
    assert strip_ids("Repay under the Housing Act 2004 (L23:s214.1, L23:s215.3). Notified (F2) [J06:p3].", lab) == \
        "Repay under the Housing Act 2004. Notified."
    assert strip_ids("Under clause F2 of the lease the tenant must repair.", lab) == \
        "Under clause F2 of the lease the tenant must repair."
