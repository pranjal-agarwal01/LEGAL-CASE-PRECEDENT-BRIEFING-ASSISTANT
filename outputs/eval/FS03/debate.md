# Debate transcript: Hughes v PeakFit Ltd

Mode: offline · LLM calls: 0

## Round 1: Argument Agent (client)

- **A1.1** [I1] Merritt v Merritt [1970] 1 WLR 1211 supports Megan Hughes on this issue: When spouses are not living in amity the presumption against intention to create legal relations does not apply, and written terms point towards an intention to be bound. That reasoning applies here: More than 3,000 people downloaded the app during the promotion. PeakFit says it never expected to be legally bound to pay all of them and that the advertisement was obvious marketing puff. — *Merritt v Merritt* [1970] 1 WLR 1211, ¶3; Fact sheet ¶6
- **A1.2** [I1] Carlill v Carbolic Smoke Ball Co [1893] 1 QB 256 supports Megan Hughes on this issue: An advertisement can be an offer where its terms are clear and it shows an intention to be bound by anyone who performs the conditions. That reasoning applies here: On 5 January 2025 PeakFit published an advertisement on its website and social media: "Complete all 100 daily PeakFit workouts by 15 April and if you have not lost 5 kg we will pay you £2,000. We have placed £100,000... — *Carlill v Carbolic Smoke Ball Co* [1893] 1 QB 256, ¶3; Fact sheet ¶1
- **A1.3** [I2] No retrieved authority squarely favours Megan Hughes on this issue, so the argument rests on the facts: PeakFit's general terms say that promotions "may be withdrawn at any time". PeakFit did not withdraw this promotion before 15 April 2025. — Fact sheet ¶5

## Round 1: Counter-Argument Agent (other side)

- **C1.1** [I1] Balfour v Balfour [1919] 2 KB 571 supports PeakFit Ltd on this issue: In domestic and social agreements there is a presumption that the parties do not intend to be legally bound. That reasoning applies here: More than 3,000 people downloaded the app during the promotion. PeakFit says it never expected to be legally bound to pay all of them and that the advertisement was obvious marketing puff. — *Balfour v Balfour* [1919] 2 KB 571, ¶3; Fact sheet ¶6
- **C1.2** [I2] Partridge v Crittenden [1968] 1 WLR 1204 supports PeakFit Ltd on this issue: Advertisements of goods for sale are ordinarily invitations to treat rather than offers, because the advertiser has limited stock and cannot sensibly be bound to sell to everyone who replies. That reasoning applies here: On 20 April 2025 she emailed PeakFit claiming £2,000. PeakFit replied that the advertisement was a marketing promotion and only an invitation to treat, that it never accepted her as a participant, and that she should have told it when... — *Partridge v Crittenden* [1968] 1 WLR 1204, ¶3; Fact sheet ¶4
- **C1.3** [I2] Pharmaceutical Society of Great Britain v Boots Cash Chemists (Southern) Ltd [1953] 1 QB 401 supports PeakFit Ltd on this issue: Displaying goods with prices invites customers to make offers; the seller remains free to accept or refuse each offer. That reasoning applies here: More than 3,000 people downloaded the app during the promotion. PeakFit says it never expected to be legally bound to pay all of them and that the advertisement was obvious marketing puff. — *Pharmaceutical Society of Great Britain v Boots Cash Chemists (Southern) Ltd* [1953] 1 QB 401, ¶3; Fact sheet ¶6

## Round 2: Argument Agent (client)

- **A2.1** [I1] *(replies to C1.1)* Balfour v Balfour is distinguishable on its facts: A husband working in Ceylon promised to pay his wife 30 pounds a month while she remained in England for health reasons. By contrast, in this case: PeakFit's general terms say that promotions "may be withdrawn at any time". PeakFit did not withdraw this promotion before 15 April 2025. — *Balfour v Balfour* [1919] 2 KB 571, ¶1; Fact sheet ¶5
- **A2.2** [I2] *(replies to C1.2)* Partridge v Crittenden is distinguishable on its facts: Mr Partridge placed an advertisement in a magazine reading 'Bramblefinch cocks, bramblefinch hens, 25s each'. By contrast, in this case: On 20 April 2025 she emailed PeakFit claiming £2,000. PeakFit replied that the advertisement was a marketing promotion and only an invitation to treat, that it never accepted her as a participant, and that she should have told it when... — *Partridge v Crittenden* [1968] 1 WLR 1204, ¶1; Fact sheet ¶4
- **A2.3** [I2] *(replies to C1.3)* Pharmaceutical Society of Great Britain v Boots Cash Chemists (Southern) Ltd is distinguishable on its facts: Boots operated a self-service shop in which customers took medicines from open shelves and paid at a cash desk supervised by a registered pharmacist. By contrast, in this case: On 5 January 2025 PeakFit published an advertisement on its website and social media: "Complete all 100 daily PeakFit workouts by 15 April and if you have not lost 5 kg we will pay you £2,000. We have placed £100,000... — *Pharmaceutical Society of Great Britain v Boots Cash Chemists (Southern) Ltd* [1953] 1 QB 401, ¶1; Fact sheet ¶1

## Round 2: Counter-Argument Agent (other side)

- **C2.1** [I2] Fisher v Bell [1961] 1 QB 394 supports PeakFit Ltd on this issue: Goods displayed in a shop window with a price attached are an invitation to treat; the customer makes the offer. That reasoning applies here: On 5 January 2025 PeakFit published an advertisement on its website and social media: "Complete all 100 daily PeakFit workouts by 15 April and if you have not lost 5 kg we will pay you £2,000. We have placed £100,000... — *Fisher v Bell* [1961] 1 QB 394, ¶3; Fact sheet ¶1

## Shared issue list: event log

| # | Agent | Action | Issue | Detail |
|---|---|---|---|---|
| 1 | fact_extractor | add_issue | I1 | Did PeakFit Ltd intend to create legal relations, or was the promise a mere puff? [intention_legal_relations] 4 cue(s) in the fact sheet |
| 2 | fact_extractor | add_issue | I2 | Was PeakFit Ltd's communication a binding offer, rather than an invitation to treat, which Megan Hughes accepted? [offer_acceptance] 4 cue(s |
| 3 | precedent_retrieval | attach_precedents | I1 | J29, J30, J23, J33, J42 |
| 4 | precedent_retrieval | attach_precedents | I2 | J24, J23, J25, J50, J26 |
| 5 | argument | frame_issue | I1 | Did PeakFit Ltd intend to create legal relations, or was the promise a mere puff? (client needs: pro) |
| 6 | argument | mark_supporting | I1 | J30 framing review |
| 7 | argument | mark_supporting | I1 | J23 framing review |
| 8 | argument | frame_issue | I2 | Was PeakFit Ltd's communication a binding offer, rather than an invitation to treat, which Megan Hughes accepted? (client needs: pro) |
| 9 | argument | mark_supporting | I2 | J23 framing review |
| 10 | argument | note | I1 | round 1: 2 point(s) for Megan Hughes |
| 11 | argument | note | I2 | round 1: 1 point(s) for Megan Hughes |
| 12 | counter_argument | mark_opposing | I1 | J29 doctrine tag matches position |
| 13 | counter_argument | mark_opposing | I2 | J24 doctrine tag matches position |
| 14 | counter_argument | mark_opposing | I2 | J25 doctrine tag matches position |
| 15 | counter_argument | note | I1 | round 1: 1 point(s) for PeakFit Ltd |
| 16 | counter_argument | note | I2 | round 1: 2 point(s) for PeakFit Ltd |
| 17 | argument | note | I1 | round 2: 1 point(s) for Megan Hughes |
| 18 | argument | note | I2 | round 2: 2 point(s) for Megan Hughes |
| 19 | counter_argument | mark_opposing | I2 | J50 doctrine tag matches position |
| 20 | counter_argument | note | I2 | round 2: 1 point(s) for PeakFit Ltd |
| 21 | brief_compiler | resolve | I1 | Favourable: the authorities on balance support Megan Hughes, led by Merritt v Merritt; Balfour v Balfour is the main authority the other sid |
| 22 | brief_compiler | resolve | I2 | Unfavourable: the weight of authority is against Megan Hughes, chiefly Partridge v Crittenden; the best answer is to rely on Carlill v Carbo |
