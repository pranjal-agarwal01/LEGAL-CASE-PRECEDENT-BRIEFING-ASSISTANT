# Evaluation report: Legal Case Precedent Briefing Assistant

Generated 2026-11-15T17:35:42 · mode **foundry** (model `gpt-4.1-mini`) · 8 fact sheets · debate rounds 2 · top-k 5 · doctrine boost 0.35

## Headline metrics (macro average over fact sheets)

| Metric | Value |
|---|---|
| Precedent recall: retrieval (issue list) | 100% |
| Precedent recall: retrieval, text only (no doctrine boost) | 100% |
| Precedent recall: final brief | 81% |
| Citations that exist in corpus: raw compiler output | 100% |
| Case-law citations that exist: raw compiler output | 99% |
| Citations that exist in corpus: final brief | 100% |
| Claims carrying a verified citation | 100% |
| Cited judgments that are on the gold list | 57% |

Micro-averaged precedent recall: retrieval 100%, brief 81%. Citations checked: 658 raw, 654 final.

## Per fact sheet

| Case | Gold precedents | Retrieved | Cited in brief | Recall (retrieval) | Recall (text only) | Recall (brief) | Citations exist (raw) | Claim coverage | Missed | LLM fallbacks |
|---|---|---|---|---|---|---|---|---|---|---|
| FS01 | J01, J10, J08 | 17 | 7 | 100% | 100% | 67% | 100% (97) | 100% | J08 | 0 |
| FS02 | J06, J07, J04 | 15 | 7 | 100% | 100% | 100% | 100% (85) | 100% | - | 0 |
| FS03 | J23, J24, J25 | 20 | 7 | 100% | 100% | 67% | 96% (108) | 100% | J25 | 0 |
| FS04 | J37, J38, J36, J39 | 5 | 4 | 100% | 100% | 100% | 100% (77) | 100% | - | 0 |
| FS05 | J34, J35, J44 | 17 | 7 | 100% | 100% | 100% | 100% (75) | 100% | - | 0 |
| FS06 | J42, J43, J41, J40 | 20 | 3 | 100% | 100% | 50% | 100% (86) | 100% | J43, J40 | 0 |
| FS07 | J32, J31, J33 | 12 | 4 | 100% | 100% | 67% | 100% (99) | 100% | J33 | 0 |
| FS08 | J15, J16, J17 | 5 | 3 | 100% | 100% | 100% | 100% (31) | 100% | - | all (content filter) |

Cases with LLM fallbacks were (partly) answered by the offline baseline; read their numbers with that in mind.

## How to read this

- **Precedent recall** = known relevant precedents found ÷ known relevant precedents (gold list in `data/eval/gold.json`).
- **Retrieval, text only** reruns retrieval with the doctrine-metadata boost switched off, isolating the hybrid BM25 + LSA search.
- **Citations that exist** = citations resolving to a real judgment passage in `data/corpus/judgments.json` or a real fact-sheet paragraph, ÷ all citations (free-text case names included). *Raw* is the compiler's output before the citation guard; the guard then removes anything unverifiable.
- In offline mode the agents can only cite passages they retrieved, so raw citation existence is 100% by construction. With an LLM provider the same metric measures hallucinated citations.
- Briefs, debate transcripts and the shared issue list for each case are in this folder under the case id.
