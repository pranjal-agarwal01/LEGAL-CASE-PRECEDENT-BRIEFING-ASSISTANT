# Debate transcript: Rowe v Skyline Terraces Ltd

Mode: offline · LLM calls: 0

## Round 1: Argument Agent (client)

- **A1.1** [I1] Krell v Henry [1903] 2 KB 740 supports Thomas Rowe on this issue: A contract may be frustrated not only by physical impossibility but where a supervening event destroys a state of affairs which both parties regarded as the basis of the contract, even if literal performance remains possible. That reasoning applies here: On 10 May 2025 Mr Rowe agreed to hire Skyline's rooftop terrace for the evening of 5 July 2025 for £12,000 and paid a £4,000 deposit. — *Krell v Henry* [1903] 2 KB 740, ¶3; Fact sheet ¶1
- **A1.2** [I1] Taylor v Caldwell (1863) 3 B & S 826 supports Thomas Rowe on this issue: Where performance depends on the continued existence of a specific thing, the destruction of that thing without fault discharges the contract. That reasoning applies here: The terrace, bar and staff remained available on 5 July 2025. On 29 June 2025 Mr Rowe cancelled his event and asked for his deposit back. — *Taylor v Caldwell* (1863) 3 B & S 826, ¶3; Fact sheet ¶5

## Round 1: Counter-Argument Agent (other side)

- **C1.1** [I1] Davis Contractors Ltd v Fareham Urban District Council [1956] AC 696 supports Skyline Terraces Ltd on this issue: Frustration occurs only where, without default of either party, a contractual obligation has become incapable of being performed because the circumstances would render it a thing radically different from that which was undertaken. That reasoning applies here: Skyline refuses to return the deposit and claims the £8,000 balance. It says the terrace could still be used, that the fireworks were only Mr Rowe's own commercial purpose, and that the event simply became less attractive. — *Davis Contractors Ltd v Fareham Urban District Council* [1956] AC 696, ¶3; Fact sheet ¶6
- **C1.2** [I1] Herne Bay Steam Boat Co v Hutton [1903] 2 KB 683 supports Skyline Terraces Ltd on this issue: Frustration does not apply where the event defeats only one party's purpose or makes the bargain less profitable; the risk of the venture falling short lies on the party who undertook it. That reasoning applies here: The terrace, bar and staff remained available on 5 July 2025. On 29 June 2025 Mr Rowe cancelled his event and asked for his deposit back. — *Herne Bay Steam Boat Co v Hutton* [1903] 2 KB 683, ¶3; Fact sheet ¶5

## Round 2: Argument Agent (client)

- **A2.1** [I1] *(replies to C1.1)* Davis Contractors Ltd v Fareham Urban District Council is distinguishable on its facts: Contractors agreed to build 78 houses for a fixed price within eight months. By contrast, in this case: The written hire agreement described only "exclusive use of the terrace, 6pm to midnight, with bar service" and did not mention the fireworks. — *Davis Contractors Ltd v Fareham Urban District Council* [1956] AC 696, ¶1; Fact sheet ¶3
- **A2.2** [I1] *(replies to C1.2)* Herne Bay Steam Boat Co v Hutton is distinguishable on its facts: Hutton chartered a steamboat to take paying passengers to see the naval review at Spithead and to cruise round the fleet. By contrast, in this case: On 28 June 2025 the council cancelled the fireworks display after a safety review. — *Herne Bay Steam Boat Co v Hutton* [1903] 2 KB 683, ¶1; Fact sheet ¶4

## Round 2: Counter-Argument Agent (other side)


## Shared issue list: event log

| # | Agent | Action | Issue | Detail |
|---|---|---|---|---|
| 1 | fact_extractor | add_issue | I1 | Was the contract frustrated by a supervening event that destroyed its common foundation? [frustration] 4 cue(s) in the fact sheet |
| 2 | precedent_retrieval | attach_precedents | I1 | J37, J39, J38, J36, J01 |
| 3 | argument | frame_issue | I1 | Was the contract frustrated by a supervening event that destroyed its common foundation? (client needs: pro) |
| 4 | argument | mark_supporting | I1 | J37 framing review |
| 5 | argument | mark_supporting | I1 | J36 framing review |
| 6 | argument | note | I1 | round 1: 2 point(s) for Thomas Rowe |
| 7 | counter_argument | mark_opposing | I1 | J39 doctrine tag matches position |
| 8 | counter_argument | mark_opposing | I1 | J38 doctrine tag matches position |
| 9 | counter_argument | note | I1 | round 1: 2 point(s) for Skyline Terraces Ltd |
| 10 | argument | note | I1 | round 2: 2 point(s) for Thomas Rowe |
| 11 | brief_compiler | resolve | I1 | Finely balanced: Krell v Henry supports Thomas Rowe, but Davis Contractors Ltd v Fareham Urban District Council gives the other side a real  |
