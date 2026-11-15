import asyncio

from legal_brief.agents import CaseSession, FactExtractorAgent
from legal_brief.doctrines import detect_doctrines
from legal_brief.factsheet import load_fact_sheet
from legal_brief.memory import IssueBoard
from legal_brief.retrieval import HybridRetriever


def test_corpus_loads(corpus):
    assert len(corpus) == 50
    assert corpus.get("J01").name == "Donoghue v Stevenson"
    assert corpus.passage("J06:p3") is not None
    assert corpus.find_by_name("Caparo v Dickman").id == "J02"
    assert corpus.find_by_name("Pharmaceutical Society of Great Britain v Boots").id == "J25"
    assert corpus.find_by_name("Smith v Imaginary Widgets Ltd") is None
    # short forms seen in real model output
    assert corpus.find_by_name("Robinson v Chief Constable and").id == "J19"
    assert corpus.find_by_name("Robinson v Chief Constable").id == "J19"
    assert corpus.find_by_name("Alcock v Chief Constable").id == "J15"
    assert corpus.find_by_name("Jones v Chief Constable") is None


def test_text_only_retrieval_finds_landmarks(corpus):
    r = HybridRetriever(corpus, doctrine_boost=0.0)
    top = [h.judgment_id for h in r.search("advertisement promising a reward, money deposited in a bank to show sincerity", top_k=3)]
    assert top[0] == "J23"
    top = [h.judgment_id for h in r.search("hired a flat to watch a procession which was cancelled", top_k=3)]
    assert "J37" in top
    top = [h.judgment_id for h in r.search("hotel bedroom notice excluding liability seen after booking at reception", top_k=3)]
    assert "J42" in top


def test_doctrine_boost_promotes_tagged_judgments(corpus):
    query = "the event was cancelled and the hirer wants the deposit back"
    tagged = {"J36", "J37", "J38", "J39"}
    plain = HybridRetriever(corpus, doctrine_boost=0.0).search(query, top_k=4, doctrine="frustration")
    boosted = HybridRetriever(corpus, doctrine_boost=0.35).search(query, top_k=4, doctrine="frustration")
    n_plain = len(tagged & {h.judgment_id for h in plain})
    n_boost = len(tagged & {h.judgment_id for h in boosted})
    assert n_boost > n_plain and n_boost >= 2
    strong = HybridRetriever(corpus, doctrine_boost=1.0).search(query, top_k=4, doctrine="frustration")
    assert {h.judgment_id for h in strong} == tagged and all(h.boosted for h in strong)


def test_fact_sheet_parsing_and_doctrines(fs_dir):
    fs = load_fact_sheet(fs_dir / "FS01_nair_v_brightwater.md")
    assert fs.case_id == "FS01" and fs.title == "Nair v Brightwater Beverages Ltd"
    assert [p.ref for p in fs.paragraphs][-1] == "F8" and fs.paragraphs[-1].kind == "objective"
    assert [k for k, _ in detect_doctrines(fs.raw_text)] == ["duty_of_care", "causation", "remoteness_tort"]


def test_fact_extractor_offline(settings, corpus, fs_dir):
    fs = load_fact_sheet(fs_dir / "FS08_clarke_v_dunmore.md")
    session = CaseSession(settings=settings, corpus=corpus, retriever=HybridRetriever(corpus), fact_sheet=fs)
    facts = asyncio.run(FactExtractorAgent(session).run())
    assert facts.client_role == "claimant"
    assert facts.claimant_label == "Helen Clarke and Ryan Clarke"
    assert facts.defendant_label == "Dunmore Haulage Ltd"
    assert facts.chronology[0].iso_date == "2024-11-21" and facts.chronology[0].fact_ref == "F1"
    # candidate issues are written to the shared issue list, attributed to the extractor
    assert [i.doctrine for i in session.board.issues] == ["psychiatric_harm"]
    assert session.board.events[0].author == "fact_extractor"


def test_issue_board_deduplicates_and_logs():
    b = IssueBoard()
    i1 = b.add_issue("Q1?", "frustration", "a")
    i2 = b.add_issue("Q1 again?", "frustration", "b")
    assert i1 is i2 and len(b.issues) == 1
    b.mark_stance(i1.id, "J37", "supporting", "argument")
    b.mark_stance(i1.id, "J38", "opposing", "counter_argument")
    assert i1.supporting == ["J37"] and i1.opposing == ["J38"]
    assert [e.action for e in b.events] == ["add_issue", "duplicate_issue_ignored", "mark_supporting", "mark_opposing"]
