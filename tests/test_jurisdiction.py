"""Research never mixes legal systems: wrong-jurisdiction facts are blocked before any research."""

import asyncio

import pytest

from legal_brief.corpus import Corpus
from legal_brief.factsheet import parse_fact_sheet
from legal_brief.jurisdiction import JurisdictionBlocked, detect_offline, normalise
from legal_brief.orchestration import run_case

INDIA = """# Fact Sheet FS30: Hardeep Singh v Gurpreet Singh
Acting for: Plaintiff
{juris}

## Parties
- Plaintiff: Hardeep Singh
- Defendant: Gurpreet Singh

## Facts
1. In 2018 Hardeep Singh bought 2 kanals of agricultural land at Village Baddowal, Ludhiana, Punjab under a registered sale deed, and mutation was sanctioned in his name.
2. Gurpreet Singh owns the adjoining 1 kanal, bought in 2016 from the same vendor.
3. In April 2025 Gurpreet Singh built a wall and shed on a 5 marla strip. The tehsildar's demarcation report of August 2025 shows encroachment.

## Client's objective
Recover possession of the 5 marlas and remove the wall.
"""

LEEDS = """# Fact Sheet FS31: Singh v Singh
Acting for: Claimant
{juris}

## Parties
- Claimant: Hardeep Singh
- Defendant: Gurpreet Singh

## Facts
1. Hardeep Singh owns a house on Cranbrook Avenue, Leeds, registered at HM Land Registry, and pays council tax to Leeds City Council.
2. In March 2025 his neighbour built a garden wall 40 centimetres over the boundary shown on the title plan, and the county court has listed the claim.
3. The neighbour refuses to move it. The surveyor's fee was £1,200.

## Client's objective
Have the wall removed.
"""


def test_normalise_and_offline_cues():
    assert normalise("Indian law (Punjab)") == "India" and normalise("england") == "England and Wales"
    assert normalise("") == "India"  # Precedent researches Indian law by default
    j, cues = detect_offline(INDIA)
    assert j == "India" and len(cues) >= 3


def test_matters_default_to_indian_law():
    assert parse_fact_sheet(INDIA.format(juris="")).jurisdiction == "India"


def test_names_never_decide_the_jurisdiction():
    # the same parties in a Leeds boundary dispute: no Indian cues, whatever the parties' names
    leeds = ("Hardeep Singh owns a house on Cranbrook Avenue, Leeds, registered at HM Land Registry. His neighbour "
             "Gurpreet Singh built a garden wall 40 centimetres over the boundary on the title plan.")
    assert detect_offline(leeds)[0] != "India"


def test_matter_set_to_another_country_has_no_library(settings):
    fs = parse_fact_sheet(LEEDS.format(juris="Jurisdiction: England and Wales"))
    with pytest.raises(JurisdictionBlocked) as e:  # the library holds only Indian law
        asyncio.run(run_case(fs, settings))
    assert e.value.kind == "no_library"


def test_indian_matter_researches_only_indian_authorities(settings):
    from legal_brief.corpus import Judgment, Passage, load_library
    from legal_brief.retrieval import HybridRetriever

    english = Judgment("U9", "Land Registration Act 2002", "", "Parliament", 2002, "property", {}, (
        Passage("U9", "s58", "provision", "58. Conclusiveness. If a person is entered in the register as the "
                "proprietor of a legal estate, the legal estate shall be deemed to be vested in him.", label="s 58"),),
        kind="legislation", jurisdiction="England and Wales")
    lib = Corpus.merge(load_library(settings), Corpus([english]))
    fs = parse_fact_sheet(INDIA.format(juris="Jurisdiction: India"))
    result = asyncio.run(run_case(fs, settings, retriever=HybridRetriever(lib.for_jurisdiction("India"))))
    cited = {c.split(":")[0] for st in result.brief.statements() for c in st.citations if not c.startswith("F")}
    assert cited and "U9" not in cited  # no English statute leaks into an Indian brief
