# Evaluation report: Legal Case Precedent Briefing Assistant

Generated 2026-11-15T17:14:01 · mode **foundry** (model `gpt-4.1-mini`) · 8 fact sheets · debate rounds 2 · top-k 5 · doctrine boost 0.35

## Headline metrics (macro average over fact sheets)

| Metric | Value |
|---|---|
| Precedent recall: retrieval (issue list) | 100% |
| Precedent recall: retrieval, text only (no doctrine boost) | 100% |
| Precedent recall: final brief | 82% |
| Citations that exist in corpus: raw compiler output | 99% |
| Case-law citations that exist: raw compiler output | 98% |
| Citations that exist in corpus: final brief | 100% |
| Claims carrying a verified citation | 100% |
| Cited judgments that are on the gold list | 57% |

Micro-averaged precedent recall: retrieval 100%, brief 81%. Citations checked: 619 raw, 611 final.

## Per fact sheet

| Case | Gold precedents | Retrieved | Cited in brief | Recall (retrieval) | Recall (text only) | Recall (brief) | Citations exist (raw) | Claim coverage | Missed |
|---|---|---|---|---|---|---|---|---|---|
| FS01 | J01, J10, J08 | 15 | 10 | 100% | 100% | 100% | 100% (93) | 100% | - |
| FS02 | J06, J07, J04 | 18 | 7 | 100% | 100% | 100% | 100% (75) | 100% | - |
| FS03 | J23, J24, J25 | 13 | 5 | 100% | 100% | 67% | 97% (93) | 100% | J25 |
| FS04 | J37, J38, J36, J39 | 22 | 7 | 100% | 100% | 75% | 100% (110) | 100% | J39 |
| FS05 | J34, J35, J44 | 22 | 9 | 100% | 100% | 100% | 93% (76) | 100% | - |
| FS06 | J42, J43, J41, J40 | 17 | 2 | 100% | 100% | 50% | 100% (77) | 100% | J41, J40 |
| FS07 | J32, J31, J33 | 12 | 3 | 100% | 100% | 67% | 100% (64) | 100% | J33 |
| FS08 | J15, J16, J17 | 5 | 3 | 100% | 100% | 100% | 100% (31) | 100% | - |

## How to read this

- **Precedent recall** = known relevant precedents found ÷ known relevant precedents (gold list in `data/eval/gold.json`).
- **Retrieval, text only** reruns retrieval with the doctrine-metadata boost switched off, isolating the hybrid BM25 + LSA search.
- **Citations that exist** = citations resolving to a real judgment passage in `data/corpus/judgments.json` or a real fact-sheet paragraph, ÷ all citations (free-text case names included). *Raw* is the compiler's output before the citation guard; the guard then removes anything unverifiable.
- In offline mode the agents can only cite passages they retrieved, so raw citation existence is 100% by construction. With an LLM provider the same metric measures hallucinated citations.
- Briefs, debate transcripts and the shared issue list for each case are in this folder under the case id.
