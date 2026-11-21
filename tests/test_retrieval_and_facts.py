import asyncio

from legal_brief.agents import CaseSession, FactExtractorAgent
from legal_brief.doctrines import detect_doctrines
from legal_brief.factsheet import load_fact_sheet
from legal_brief.memory import IssueBoard
from legal_brief.retrieval import HybridRetriever


def test_library_file_loads(corpus):
    assert len(corpus) == 12
    j = corpus.get("J240778")
    assert j.court == "Supreme Court of India" and "2024 INSC 778" in j.citation and j.jurisdiction == "India"
    # the reporter's headnote is kept apart from the court's own paragraphs
    assert any(p.section == "headnote" and p.pid.startswith("h") for p in j.passages)
    assert any(p.section == "paragraph" for p in j.passages)
    assert corpus.find_by_name("Janardan Das v Durga Prasad Agarwalla").id == "J240778"
    assert corpus.find_by_name("Kusum Lata Sharma v Arvind Singh").id == "J230429"
    assert corpus.find_by_name("Ram Prasad v Shyam Lal") is None


def test_text_only_retrieval_finds_the_right_judgments(corpus):
    r = HybridRetriever(corpus, doctrine_boost=0.0)
    top = [h.judgment_id for h in r.search("purchaser did not prove readiness and willingness to pay the balance", top_k=3)]
    assert "J240778" in top
    top = [h.judgment_id for h in r.search("landlord needs the shop for her son, bona fide requirement", top_k=3)]
    assert top[0] in {"J230429", "J190159"}
    top = [h.judgment_id for h in r.search("sale deed executed while the suit was pending, lis pendens", top_k=3)]
    assert {"J240770", "J240377"} & set(top)
    top = [h.judgment_id for h in r.search("daughter is a coparcener by birth after the 2005 amendment", top_k=3)]
    assert top[0] == "J200487"


def test_fact_sheet_parsing_and_doctrines(fs_dir):
    fs = load_fact_sheet(fs_dir / "FS01_reddy_v_srinivasulu.md")
    assert fs.case_id == "FS01" and fs.title == "Reddy v Srinivasulu" and fs.jurisdiction == "India"
    assert [p.ref for p in fs.paragraphs][-1] == "F7" and fs.paragraphs[-1].kind == "objective"
    assert [k for k, _ in detect_doctrines(fs.raw_text)] == ["readiness_willingness", "specific_performance"]
    fs4 = load_fact_sheet(fs_dir / "FS04_kaur_v_dhillon.md")
    assert {k for k, _ in detect_doctrines(fs4.raw_text)} >= {"lis_pendens", "bona_fide_purchaser"}


def test_fact_extractor_offline(settings, corpus, fs_dir):
    fs = load_fact_sheet(fs_dir / "FS04_kaur_v_dhillon.md")
    session = CaseSession(settings=settings, corpus=corpus, retriever=HybridRetriever(corpus), fact_sheet=fs)
    facts = asyncio.run(FactExtractorAgent(session).run())
    assert facts.client_role == "claimant"  # "Acting for: Plaintiff"
    assert facts.claimant_label == "Gurpreet Kaur"
    assert facts.defendant_label == "Jaswinder Dhillon and Amarjit Gill"
    assert facts.chronology[0].iso_date == "2017-06-15" and facts.chronology[0].fact_ref == "F1"
    assert "lis_pendens" in [i.doctrine for i in session.board.issues]
    assert session.board.events[0].author == "fact_extractor"


def test_issue_board_deduplicates_and_logs():
    b = IssueBoard()
    i1 = b.add_issue("Q1?", "adverse_possession", "a")
    i2 = b.add_issue("Q1 again?", "adverse_possession", "b")
    assert i1 is i2 and len(b.issues) == 1
    b.mark_stance(i1.id, "J240875", "supporting", "argument")
    b.mark_stance(i1.id, "J250956", "opposing", "counter_argument")
    assert i1.supporting == ["J240875"] and i1.opposing == ["J250956"]
    assert [e.action for e in b.events] == ["add_issue", "duplicate_issue_ignored", "mark_supporting", "mark_opposing"]


def test_split_legislation_skips_contents_and_footnotes():
    from legal_brief.ingest import split_legislation

    act = "\n".join([
        "THE EXAMPLE ACT, 1963", "ARRANGEMENT OF SECTIONS", "1. Short title.", "2. Recovery of land.",
        "3. Injunctions.", "THE SCHEDULE.", "THE EXAMPLE ACT, 1963", "ACT NO. 9 OF 1963",
        "BE it enacted by Parliament as follows:—",
        "1. Short title.—(1) This Act may be called the Example Act, 1963.",
        "2. Recovery of land.—A person entitled to the possession of land may recover it.",
        "1. Subs. by Act 18 of 1977, s. 2, for certain words.",
        "2A. Inserted section.—A new rule inserted later.",
        "3. Injunctions.—A perpetual injunction may be granted to prevent the breach of an obligation.",
        "THE SCHEDULE", "Description of suit Period", "1. For a debt. Three years.", "2. For land. Twelve years.",
        "3. For possession of immovable property based on title. Twelve years. When possession becomes adverse.",
    ])
    paras = {p.pid: p for p in split_legislation(act)}
    assert {"s1", "s2", "s2A", "s3", "art1", "art2", "art3"} <= set(paras)
    assert paras["s2"].text.startswith("Recovery of land.—A person entitled")  # body text, not the contents line
    assert "Subs. by" not in paras["s2"].text  # page footnote dropped
    assert paras["art3"].label == "Sch, art 3" and "based on title" in paras["art3"].text


def test_supreme_court_metadata_from_text():
    from legal_brief.ingest import regex_metadata

    head = ("[2025] 11 S.C.R. 423 : 2025 INSC 1286\nP. Anjanappa (D) By Lrs\nv.\nA.P. Nanjundappa & Ors.\n"
            "(Civil Appeal No. 3934 of 2006)\n06 November 2025\n" + "The suit for partition was decreed. " * 40)
    m = regex_metadata(head, "x.pdf")
    assert m.court == "Supreme Court of India" and m.jurisdiction == "India"
    assert m.citation.startswith("2025 INSC 1286") and m.date == "2025-11-06"
