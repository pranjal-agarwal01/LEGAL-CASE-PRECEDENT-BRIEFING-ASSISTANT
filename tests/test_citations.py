from legal_brief.citations import CitationValidator, audit_brief, guard_brief
from legal_brief.factsheet import load_fact_sheet
from legal_brief.models import Brief, CitedStatement, IssueAnalysis


def _validator(corpus, fs_dir):
    return CitationValidator(corpus, load_fact_sheet(fs_dir / "FS01_reddy_v_srinivasulu.md"))


def test_citation_ids(corpus, fs_dir):
    v = _validator(corpus, fs_dir)
    assert v.check("J240778:p8.1").valid
    assert v.check("[j240778:P9]").valid  # normalised
    assert v.check("J240778").valid
    assert v.check("J240778:h1").valid  # a headnote part
    assert v.check("J240778:p999").status == "unknown_passage"
    assert v.check("J999999:p1").status == "unknown_judgment"
    assert v.check("F3").valid and v.check("F42").status == "unknown_fact"
    assert v.check("Janardan 2024").status == "malformed"


def test_case_names_in_text(corpus, fs_dir):
    v = _validator(corpus, fs_dir)
    ok = v.case_names("As in Janardan Das v Durga Prasad Agarwalla, readiness must be continuous.")
    assert [c.valid for c in ok] == [True]
    bad = v.case_names("See also Ramesh Kumar v Suresh Chand for the same point.")
    assert [c.status for c in bad] == ["unknown_case_name"]
    assert v.case_names("Reddy v Srinivasulu is the client's own case.") == []


def test_guard_removes_hallucinated_citations(corpus, fs_dir):
    v = _validator(corpus, fs_dir)
    brief = Brief(
        case_id="FS01", title="Reddy v Srinivasulu", acting_for="Defendant",
        summary=[CitedStatement(text="Readiness must be proved.", citations=["J240778:p8.1", "J999999:p4"]),
                 CitedStatement(text="Ramesh Kumar v Suresh Chand decides this.", citations=["J240778:p9"]),
                 CitedStatement(text="An uncited assertion.", citations=[])],
        issues=[IssueAnalysis(issue_id="I1", question="Readiness?",
                              assessment=CitedStatement(text="Favourable [J240778:p9].", citations=["F4"]))],
    )
    raw = audit_brief(brief, v)
    assert raw.total == 6 and raw.valid == 4  # J999999:p4 and the invented case name do not exist
    final, warnings = guard_brief(brief, v)
    assert [s.citations for s in final.summary] == [["J240778:p8.1"]]
    assert final.issues[0].assessment.text == "Favourable."
    assert final.issues[0].assessment.citations == ["F4", "J240778:p9"]  # inline citation kept as structured
    rep = audit_brief(final, v)
    assert rep.existence_rate == 1.0 and rep.coverage == 1.0
    assert len(warnings) == 3


def test_quote_fallback_uses_a_real_sentence(corpus):
    from legal_brief.verification import _best_sentence

    pairs = [(p.ref, p.text) for p in corpus.get("J240778").passages]
    # a paraphrase of the passage: the real sentence is chosen, copied verbatim from the source
    ref, sentence = _best_sentence(pairs, "a plaintiff seeking specific performance must prove they were always "
                                          "ready and willing to perform the essential terms of the contract")
    assert ref.startswith("J240778:") and sentence in corpus.passage(ref).text
    # an unrelated claim finds no sentence, so no quote is shown
    assert _best_sentence(pairs, "the employer failed to pay the statutory minimum wage") is None


def test_ids_in_prose_become_readable():
    import re

    from legal_brief.citations import render_citation, strip_ids
    from legal_brief.corpus import Corpus, Judgment, Passage

    acts = Corpus([
        Judgment("L02", "Specific Relief Act, 1963", "", "Parliament of India", 1963, "property", {}, (
            Passage("L02", "s16", "provision", "16. Personal bars to relief.", label="s 16"),), kind="legislation"),
        Judgment("L03", "Limitation Act, 1963", "", "Parliament of India", 1963, "property", {}, (
            Passage("L03", "art54", "provision", "54. For specific performance of a contract. Three years.",
                    label="Sch, art 54"),), kind="legislation"),
    ])
    lab = lambda c: re.sub(r"\s*\(part \d+ of \d+\)", "", render_citation(c, acts).replace("*", ""))  # noqa: E731
    assert strip_ids("Readiness must be pleaded (SRA s 16(c): L02:s16, facts F1).", lab) == \
        "Readiness must be pleaded (SRA s 16(c))."
    assert strip_ids("The suit had to be filed by 3 September 2022 (calculate from F2 and L03:art54).", lab) == \
        "The suit had to be filed by 3 September 2022 (calculate from fact ¶2 and Limitation Act, 1963, Sch, art 54)."
    assert strip_ids("Under clause F2 of the agreement the buyer must pay.", lab) == \
        "Under clause F2 of the agreement the buyer must pay."
