# Evaluation report: Legal Case Precedent Briefing Assistant

Generated 2026-11-15T17:38:34 · mode **offline** (model `gpt-4.1-mini`) · 8 fact sheets · debate rounds 2 · top-k 5 · doctrine boost 0.35

## Headline metrics (macro average over fact sheets)

| Metric | Value |
|---|---|
| Precedent recall: retrieval (issue list) | 100% |
| Precedent recall: retrieval, text only (no doctrine boost) | 100% |
| Precedent recall: final brief | 100% |
| Citations that exist in corpus: raw compiler output | 100% |
| Case-law citations that exist: raw compiler output | 100% |
| Citations that exist in corpus: final brief | 100% |
| Claims carrying a verified citation | 100% |
| Cited judgments that are on the gold list | 69% |

Micro-averaged precedent recall: retrieval 100%, brief 100%. Citations checked: 413 raw, 413 final.

## Per fact sheet

| Case | Gold precedents | Retrieved | Cited in brief | Recall (retrieval) | Recall (text only) | Recall (brief) | Citations exist (raw) | Claim coverage | Missed | LLM fallbacks |
|---|---|---|---|---|---|---|---|---|---|---|
| FS01 | J01, J10, J08 | 14 | 10 | 100% | 100% | 100% | 100% (84) | 100% | - | 0 |
| FS02 | J06, J07, J04 | 10 | 6 | 100% | 100% | 100% | 100% (68) | 100% | - | 0 |
| FS03 | J23, J24, J25 | 9 | 6 | 100% | 100% | 100% | 100% (59) | 100% | - | 0 |
| FS04 | J37, J38, J36, J39 | 5 | 4 | 100% | 100% | 100% | 100% (35) | 100% | - | 0 |
| FS05 | J34, J35, J44 | 10 | 7 | 100% | 100% | 100% | 100% (60) | 100% | - | 0 |
| FS06 | J42, J43, J41, J40 | 5 | 5 | 100% | 100% | 100% | 100% (43) | 100% | - | 0 |
| FS07 | J32, J31, J33 | 5 | 3 | 100% | 100% | 100% | 100% (33) | 100% | - | 0 |
| FS08 | J15, J16, J17 | 5 | 3 | 100% | 100% | 100% | 100% (31) | 100% | - | 0 |

## How to read this

- **Precedent recall** = known relevant precedents found ÷ known relevant precedents (gold list in `data/eval/gold.json`).
- **Retrieval, text only** reruns retrieval with the doctrine-metadata boost switched off, isolating the hybrid BM25 + LSA search.
- **Citations that exist** = citations resolving to a real judgment passage in `data/corpus/judgments.json` or a real fact-sheet paragraph, ÷ all citations (free-text case names included). *Raw* is the compiler's output before the citation guard; the guard then removes anything unverifiable.
- In offline mode the agents can only cite passages they retrieved, so raw citation existence is 100% by construction. With an LLM provider the same metric measures hallucinated citations.
- Briefs, debate transcripts and the shared issue list for each case are in this folder under the case id.
