"""Research never mixes legal systems: wrong-jurisdiction facts are blocked before any research."""

import asyncio

import pytest

from legal_brief.corpus import Corpus, Judgment, Passage
from legal_brief.factsheet import parse_fact_sheet
from legal_brief.jurisdiction import JurisdictionBlocked, detect_offline, normalise
from legal_brief.orchestration import run_case

INDIA = """# Fact Sheet FS30: Hardeep Singh v Gurpreet Singh
Acting for: Claimant
{juris}

## Parties
- Claimant: Hardeep Singh
- Defendant: Gurpreet Singh

## Facts
1. In 2018 Hardeep Singh bought 2 kanals of agricultural land at Village Baddowal, Ludhiana, Punjab under a registered sale deed, and mutation was sanctioned in his name.
2. Gurpreet Singh owns the adjoining 1 kanal, bought in 2016 from the same vendor.
3. In April 2025 Gurpreet Singh built a wall and shed on a 5 marla strip. The tehsildar's demarcation report of August 2025 shows encroachment.

## Client's objective
Recover possession of the 5 marlas and remove the wall.
"""


def test_normalise_and_offline_cues():
    assert normalise("Indian law (Punjab)") == "India" and normalise("england") == "England and Wales"
    j, cues = detect_offline(INDIA)
    assert j == "India" and len(cues) >= 3


def test_indian_facts_are_blocked_under_english_law(settings):
    fs = parse_fact_sheet(INDIA.format(juris=""))
    assert fs.jurisdiction == "England and Wales"
    with pytest.raises(JurisdictionBlocked) as e:
        asyncio.run(run_case(fs, settings))
    assert e.value.kind == "mismatch" and e.value.as_dict()["detected"] == "India"


def test_indian_matter_needs_indian_authorities(settings):
    fs = parse_fact_sheet(INDIA.format(juris="Jurisdiction: India"))
    with pytest.raises(JurisdictionBlocked) as e:  # the default library holds only England and Wales law
        asyncio.run(run_case(fs, settings))
    assert e.value.kind == "no_library"


def test_indian_matter_researches_only_indian_authorities(settings):
    sra = Judgment("U1", "Specific Relief Act, 1963", "", "Parliament of India", 1963, "property", {}, (
        Passage("U1", "s5", "provision", "5. Recovery of specific immovable property. A person entitled to the "
                "possession of specific immovable property may recover it in the manner provided by the Code of "
                "Civil Procedure, 1908.", label="s 5"),
        Passage("U1", "s38", "provision", "38. Perpetual injunction when granted. A perpetual injunction may be "
                "granted to the plaintiff to prevent the breach of an obligation existing in his favour.",
                label="s 38")), kind="legislation", jurisdiction="India")
    from legal_brief.config import Settings
    from legal_brief.corpus import load_library
    from legal_brief.retrieval import HybridRetriever

    lib = Corpus.merge(load_library(Settings().with_overrides(include_legislation=True)), Corpus([sra]))
    fs = parse_fact_sheet(INDIA.format(juris="Jurisdiction: India"))
    result = asyncio.run(run_case(fs, settings, retriever=HybridRetriever(lib.for_jurisdiction("India"))))
    cited = {c.split(":")[0] for st in result.brief.statements() for c in st.citations if not c.startswith("F")}
    assert cited <= {"U1"}, cited  # no English statute or case summary leaks into an Indian brief
