# Debate transcript: Brennan Joinery Ltd v Castlegate Developments Ltd

Mode: llm:foundry · LLM calls: 9

## Round 1: Argument Agent (client)

- **A1.1** [I1] The promise by Castlegate to pay Brennan an extra £1,000 per house completed on time constitutes a valid contract variation supported by fresh consideration because Castlegate obtained a practical benefit: avoiding the developer's penalty and the trouble of finding another joiner, as in Williams v Roffey Bros, where practical benefit sufficed for consideration without economic duress or fraud (J32:p3; F2, F4, F5, F6). — *Williams v Roffey Bros & Nicholls (Contractors) Ltd* [1991] 1 QB 1, ¶3; Fact sheet ¶2; Fact sheet ¶4; Fact sheet ¶5; Fact sheet ¶6
- **A1.2** [I2] Alternatively, Castlegate's promise is enforceable under promissory estoppel as it was intended to be binding and acted upon by Brennan completing the houses on schedule, analogous to the High Trees case where a promise intended and acted upon precluded denial even absent consideration (J33:p3; F4, F5). — *Central London Property Trust Ltd v High Trees House Ltd* [1947] KB 130, ¶3; Fact sheet ¶4; Fact sheet ¶5

## Round 1: Counter-Argument Agent (other side)

- **C1.1** [I1] *(replies to A1.1)* The promise of extra payment by Castlegate is unenforceable for want of consideration because Brennan was already contractually obliged to complete the kitchens and staircases in the 30 houses by 30 June 2025, so performance of this existing duty does not constitute good consideration for the additional £18,000 promised. This principle was firmly established in Stilk v Myrick, where performance of an existing contractual duty owed to the promisor was held not to be good consideration for extra payment. — *Stilk v Myrick* (1809) 2 Camp 317, ¶2; *Stilk v Myrick* (1809) 2 Camp 317, ¶3; Fact sheet ¶1; Fact sheet ¶5

## Round 2: Argument Agent (client)

- **A2.1** [I1] *(replies to C1.1)* The promise of extra payment by Castlegate is supported by consideration because it conferred a practical benefit on Castlegate by ensuring timely completion and avoiding costly penalties, consistent with the Court of Appeal's decision in Williams v Roffey Bros, where similar facts led to recognition of a valid contract variation for practical benefit without economic duress or fraud (J32:p2, J32:p3; F2, F4, F5, F6). — *Williams v Roffey Bros & Nicholls (Contractors) Ltd* [1991] 1 QB 1, ¶2; *Williams v Roffey Bros & Nicholls (Contractors) Ltd* [1991] 1 QB 1, ¶3; Fact sheet ¶2; Fact sheet ¶4; Fact sheet ¶5; Fact sheet ¶6
- **A2.2** [I2] Even if consideration were absent, Castlegate's clear promise to pay extra was intended to be binding and acted upon by Brennan, creating an estoppel preventing Castlegate from reneging, following the principle in High Trees that such promises made and relied upon are enforceable to avoid injustice (J33:p3; F4, F5). — *Central London Property Trust Ltd v High Trees House Ltd* [1947] KB 130, ¶3; Fact sheet ¶4; Fact sheet ¶5

## Round 2: Counter-Argument Agent (other side)

- **C2.1** [I1] The promise of extra payment is unenforceable for lack of consideration because Brennan was contractually required to complete all 30 houses by the deadline, and performing this existing duty cannot provide fresh consideration. This position is supported by Stilk v Myrick where the court ruled that a promise to pay extra for performing an existing contractual obligation is not enforceable (J31:p2, J31:p3; F1, F5). — *Stilk v Myrick* (1809) 2 Camp 317, ¶2; *Stilk v Myrick* (1809) 2 Camp 317, ¶3; Fact sheet ¶1; Fact sheet ¶5
- **C2.2** [I1] *(replies to A2.1)* Williams v Roffey Bros does not definitively overrule Stilk v Myrick but only refines it, allowing enforceability when a practical benefit exists and there is no economic duress; however, Brennan gave no indication of refusing to perform and no alteration of obligation was made, distinguishing these facts from Roffey where financial difficulty and risk of breach justified the promise (J32:p3; F3, F6). — *Williams v Roffey Bros & Nicholls (Contractors) Ltd* [1991] 1 QB 1, ¶3; Fact sheet ¶3; Fact sheet ¶6
- **C2.3** [I2] *(replies to A2.2)* Promissory estoppel cannot create a new cause of action or independent basis for enforcing Castlegate's promise without consideration; High Trees suspends rights in the existing contract and does not support enforcement of a new sum payable for pre-existing duties (J33:p3; F4, F5). — *Central London Property Trust Ltd v High Trees House Ltd* [1947] KB 130, ¶3; Fact sheet ¶4; Fact sheet ¶5

## Shared issue list: event log

| # | Agent | Action | Issue | Detail |
|---|---|---|---|---|
| 1 | fact_extractor | add_issue | I1 | Is there a valid variation to the contract obliging Castlegate to pay the extra £18,000? [consideration_variation] The facts raise whether t |
| 2 | fact_extractor | add_issue | I2 | Can Brennan enforce Castlegate's promise on the basis of promissory estoppel? [promissory_estoppel] The promise was made to induce performan |
| 3 | fact_extractor | duplicate_issue_ignored | I1 | Did Brennan provide any new consideration beyond its original contractual obligation? |
| 4 | precedent_retrieval | attach_precedents | I1 | J32, J31, J33, J48, J29, J26 |
| 5 | precedent_retrieval | attach_precedents | I2 | J33, J32, J31, J48, J29, J23, J47 |
| 6 | argument | frame_issue | I1 | Is there a valid variation to the contract between Brennan Joinery Ltd and Castlegate Developments Ltd obliging Castlegate to pay the extra  |
| 7 | argument | frame_issue | I2 | Can Brennan Joinery Ltd enforce Castlegate Developments Ltd's promise to pay the extra £18,000 on the basis of promissory estoppel? (client  |
| 8 | argument | mark_supporting | I1 | J32 argument relies on it |
| 9 | argument | mark_supporting | I2 | J33 argument relies on it |
| 10 | argument | note | I1 | round 1: 1 point(s) for Brennan Joinery Ltd |
| 11 | argument | note | I2 | round 1: 1 point(s) for Brennan Joinery Ltd |
| 12 | counter_argument | mark_opposing | I1 | J31 counter relies on it |
| 13 | counter_argument | note | I1 | round 1: 1 point(s) for Castlegate Developments Ltd |
| 14 | argument | note | I1 | round 2: 1 point(s) for Brennan Joinery Ltd |
| 15 | argument | note | I2 | round 2: 1 point(s) for Brennan Joinery Ltd |
| 16 | counter_argument | note | I1 | round 2: 2 point(s) for Castlegate Developments Ltd |
| 17 | counter_argument | note | I2 | round 2: 1 point(s) for Castlegate Developments Ltd |
| 18 | brief_compiler | resolve | I1 | The balance of authorities favors finding a valid variation under Williams v Roffey Bros since Castlegate obtained a practical benefit preve |
| 19 | brief_compiler | resolve | I2 | Although promissory estoppel prevents Castlegate from denying the promise, it traditionally does not provide an independent cause of action  |
