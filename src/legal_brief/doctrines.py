"""A small taxonomy of legal doctrines (issue types) used across the agents.

Each doctrine knows how to phrase its issue question, which words in a fact sheet
suggest it, which search terms help retrieval, and which answer the claimant
normally wants ('pro' = the doctrine applies / liability or enforceability is
established, 'contra' = it does not). Judgments in the corpus are tagged with the
same keys, which lets the debaters split retrieved precedents into supporting and
opposing authorities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


AREA_LABELS = {"tort": "Tort (negligence)", "contract": "Contract", "property": "Landlord and tenant",
               "employment": "Employment"}


@dataclass(frozen=True)
class Doctrine:
    key: str
    label: str
    area: str  # one of AREA_LABELS
    question: str  # may use {claimant} and {defendant}
    patterns: tuple[str, ...]
    query_terms: str
    claimant_wants: str = "pro"
    defence: bool = False  # typically raised by the opposing side
    subsumes: tuple[str, ...] = field(default_factory=tuple)

    def frame(self, claimant: str, defendant: str) -> str:
        return self.question.format(claimant=claimant, defendant=defendant)


DOCTRINES: dict[str, Doctrine] = {
    d.key: d
    for d in [
        Doctrine(
            "duty_of_care", "Duty of care in negligence", "tort",
            "Did {defendant} owe {claimant} a duty of care in negligence?",
            (r"negligen\w*", r"duty of care", r"manufactur\w*", r"consumer", r"no contract", r"bottl\w*", r"sealed", r"police"),
            "duty of care negligence neighbour principle manufacturer ultimate consumer foreseeable proximity",
        ),
        Doctrine(
            "standard_of_care", "Breach: standard of care", "tort",
            "Did {defendant} fall below the standard of reasonable care?",
            (r"breach\w*", r"reasonable care", r"precaution\w*", r"careless\w*", r"learner", r"standard of care", r"goggles"),
            "breach standard of care reasonable person precautions risk probability",
            defence=True,
        ),
        Doctrine(
            "medical_standard", "Professional (Bolam) standard", "tort",
            "Did the clinician's conduct fall below the standard of a responsible body of medical opinion?",
            (r"surgeon\w*", r"clinician\w*", r"responsible (body|\w+ surgeons|doctors)", r"surgery", r"operation"),
            "responsible body of medical opinion professional practice doctor surgeon Bolam logical analysis",
            defence=True,
        ),
        Doctrine(
            "informed_consent", "Duty to warn / informed consent", "tort",
            "Did {defendant} breach the duty to warn {claimant} of material risks and reasonable alternatives before consent was given?",
            (r"warn\w*", r"consent\w*", r"\brisks?\b", r"alternative\w*", r"disclos\w*", r"material risk"),
            "duty to warn material risk informed consent reasonable alternative treatment patient autonomy",
        ),
        Doctrine(
            "causation", "Factual causation", "tort",
            "Can {claimant} prove that the breach caused the harm, on the but-for test or a modified approach?",
            (r"caus(ed|es|ing|ation)", r"would (not )?have", r"anyway", r"but for", r"tamper\w*"),
            "causation but for test would have happened anyway balance of probabilities caused the harm",
            defence=True,
        ),
        Doctrine(
            "remoteness_tort", "Remoteness and the thin skull rule", "tort",
            "Is {defendant} liable for the full extent of the harm, including harm made worse by {claimant}'s pre-existing condition?",
            (r"pre-existing", r"\bcondition\b", r"vulnerab\w*", r"more serious", r"susceptib\w*", r"thin skull|eggshell", r"unforeseeable"),
            "remoteness foreseeable kind of damage thin skull eggshell pre-existing condition take victim as found extent",
        ),
        Doctrine(
            "psychiatric_harm", "Psychiatric injury (primary and secondary victims)", "tort",
            "Can {claimant} recover for psychiatric injury, and as a primary or a secondary victim?",
            (r"psychiatric", r"post-traumatic|ptsd", r"\bshock\w*", r"nervous", r"aftermath", r"live (traffic-camera )?(stream|broadcast|television)", r"relatives?", r"mother", r"brother"),
            "psychiatric injury nervous shock secondary victim immediate aftermath close tie of love and affection own unaided senses primary victim",
            subsumes=("duty_of_care",),
        ),
        Doctrine(
            "strict_liability", "Strict liability for escapes", "tort",
            "Is {defendant} strictly liable for the escape of a dangerous thing from its land?",
            (r"escap\w*", r"reservoir", r"flood\w*", r"non-natural", r"neighbouring land"),
            "escape dangerous thing land non-natural use strict liability neighbour",
        ),
        Doctrine(
            "occupiers_liability", "Occupiers' liability", "tort",
            "Is {defendant} liable as occupier for an injury arising from the premises or an obvious risk?",
            (r"occupier\w*", r"premises", r"visitor\w*", r"trespass\w*", r"\blake\b", r"country park"),
            "occupier premises obvious risk visitor activity",
        ),
        Doctrine(
            "pure_economic_loss", "Pure economic loss", "tort",
            "Can {claimant} recover financial loss that is not consequential on physical damage?",
            (r"economic loss", r"financial loss", r"investor\w*", r"\bshares\b", r"audit\w*"),
            "pure economic loss financial loss consequential on physical damage",
        ),
        Doctrine(
            "negligent_misstatement", "Negligent misstatement", "tort",
            "Did {defendant} assume responsibility for a statement on which {claimant} reasonably relied?",
            (r"\badvice\b", r"credit reference", r"misstatement", r"relied on (the|its|his|her) (advice|statement|reference)", r"auditor\w*"),
            "negligent misstatement assumption of responsibility reliance special relationship advice",
            subsumes=("duty_of_care",),
        ),
        Doctrine(
            "offer_acceptance", "Offer, acceptance and invitation to treat", "contract",
            "Was {defendant}'s communication a binding offer, rather than an invitation to treat, which {claimant} accepted?",
            (r"advert\w*", r"\boffer(ed|s)?\b", r"accept(ed|ance)", r"invitation to treat", r"reward", r"promotion\w*", r"unilateral", r"counter-offer"),
            "offer unilateral contract advertisement invitation to treat acceptance by performance reward",
        ),
        Doctrine(
            "communication_of_acceptance", "Communication of acceptance", "contract",
            "Was acceptance effectively communicated, and was notice of acceptance required?",
            (r"posted", r"letter of acceptance", r"telex", r"notice of acceptance", r"notif\w*", r"told it when"),
            "communication of acceptance postal rule notification of acceptance instantaneous",
        ),
        Doctrine(
            "intention_legal_relations", "Intention to create legal relations", "contract",
            "Did {defendant} intend to create legal relations, or was the promise a mere puff?",
            (r"legally bound", r"legal relations", r"\bpuff\b", r"sincerity", r"mean it", r"marketing", r"spouse\w*", r"domestic"),
            "intention to create legal relations mere puff sincerity deposit domestic agreement",
            defence=True,
        ),
        Doctrine(
            "consideration_variation", "Consideration for a promise of extra payment", "contract",
            "Is {defendant}'s promise of additional payment supported by consideration?",
            (r"extra (payment|£|\d|money)", r"additional payment", r"already obliged", r"existing (contract|duty|obligation)", r"practical benefit", r"promised .{0,40}pay"),
            "consideration promise additional payment existing contractual duty practical benefit economic duress",
        ),
        Doctrine(
            "promissory_estoppel", "Promissory estoppel", "contract",
            "Is {defendant} estopped from going back on its promise because {claimant} relied on it?",
            (r"relied on (the|its|his|her) promise", r"waive\w*", r"reduc\w* (the )?rent", r"accept less", r"estop\w*", r"go(ing)? back on"),
            "promissory estoppel promise intended to be acted on relied on reduce rent",
        ),
        Doctrine(
            "remoteness_contract", "Remoteness of damage in contract", "contract",
            "Are {claimant}'s claimed losses within what the parties reasonably contemplated when they contracted?",
            (r"profit\w*", r"\bdelay\w*", r"late deliver\w*|delivered .{0,30}late", r"lucrative", r"exceptional", r"contemplat\w*", r"courier\w*|carrier\w*"),
            "remoteness damages lost profits reasonable contemplation special circumstances carrier delay Hadley",
            defence=True,
        ),
        Doctrine(
            "frustration", "Frustration", "contract",
            "Was the contract frustrated by a supervening event that destroyed its common foundation?",
            (r"frustrat\w*", r"cancel\w*", r"impossib\w*", r"destroy\w*", r"supervening", r"\bhir(e|ed|ing)\b", r"deposit"),
            "frustration supervening event foundation of the contract cancelled hire radically different impossibility",
        ),
        Doctrine(
            "exclusion_clause", "Exclusion and limitation clauses", "contract",
            "Can {defendant} rely on the exclusion clause: was it incorporated into the contract and does it cover the loss?",
            (r"exclu\w*", r"\bclause\b", r"\bnotice\b", r"terms and conditions", r"(accepts|accept) no liability", r"signed", r"\bticket\b"),
            "exclusion clause incorporation notice before contract signature construction limitation of liability",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "penalty_clause", "Penalties and liquidated damages", "contract",
            "Is the agreed sum payable on breach an unenforceable penalty?",
            (r"penalty clause", r"unenforceable penalty", r"is a penalty", r"holding fee"),
            "penalty liquidated damages genuine pre-estimate legitimate interest out of all proportion",
        ),
        Doctrine(
            "anticipatory_breach", "Anticipatory breach", "contract",
            "Did {defendant} repudiate the contract before performance was due?",
            (r"repudiat\w*", r"no longer required", r"before the date for performance"),
            "anticipatory breach repudiation before performance",
        ),
        Doctrine(
            "termination", "Termination for breach", "contract",
            "Was the innocent party entitled to terminate the contract for breach?",
            (r"terminat\w*", r"unseaworth\w*", r"innominate", r"right to end"),
            "termination innominate term deprived of substantially the whole benefit",
        ),
        # ------------------------------------------------- contract & consumer (statutory)
        Doctrine(
            "consumer_goods_rights", "Consumer rights in goods (CRA 2015 Part 1)", "contract",
            "Were the goods supplied to {claimant} of satisfactory quality, fit for purpose and as described, and which statutory remedies follow?",
            (r"\bconsumer\b", r"faulty", r"defective (goods|product|item)", r"refund", r"repair or replace\w*", r"satisfactory quality", r"fit for (its )?purpose", r"short-term right to reject"),
            "consumer rights satisfactory quality fit for particular purpose goods as described right to reject repair replacement price reduction",
        ),
        Doctrine(
            "consumer_services_rights", "Consumer rights in services", "contract",
            "Was the service provided to {claimant} with reasonable care and skill, and is {claimant} entitled to repeat performance or a price reduction?",
            (r"reasonable care and skill", r"(poor|shoddy|substandard) (work|workmanship|service)", r"\btrader\b", r"builder\w*", r"installer\w*"),
            "service performed with reasonable care and skill repeat performance price reduction trader consumer",
        ),
        Doctrine(
            "unfair_terms", "Unfair terms and statutory controls", "contract",
            "Is the term relied on by {defendant} unfair or otherwise not binding under the Consumer Rights Act 2015 or the Unfair Contract Terms Act 1977?",
            (r"unfair (term|contract term)", r"not (responsible|liable) for any", r"tenancy agreement says", r"small print", r"reasonableness", r"standard terms"),
            "unfair term not binding on the consumer significant imbalance good faith transparency reasonableness test exclusion liability negligence",
        ),
        Doctrine(
            "misrepresentation", "Misrepresentation", "contract",
            "Was {claimant} induced to enter the contract by a false statement of fact, and is rescission or damages available?",
            (r"misrepresent\w*", r"false(ly)? (statement|told|said|assur)", r"induced", r"assured (her|him|them)", r"turned out to be untrue"),
            "misrepresentation false statement of fact inducement rescission damages reasonable grounds to believe",
        ),
        Doctrine(
            "implied_terms_business", "Statutory implied terms (business contracts)", "contract",
            "Did the goods or services supplied to {claimant} breach the terms implied by statute?",
            (r"sale of goods", r"merchantable|satisfactory quality", r"supply of goods", r"b2b|business customer"),
            "implied term satisfactory quality fitness for purpose description sale of goods supply of services reasonable care and skill",
        ),
        Doctrine(
            "third_party_rights", "Third party rights under a contract", "contract",
            "Can {claimant} enforce the contract term although not a party to the contract?",
            (r"third party", r"not a party to the contract", r"for the benefit of"),
            "third party enforce term contract purports to confer benefit rights of third parties",
        ),
        Doctrine(
            "consumer_cancellation", "Distance and off-premises cancellation rights", "contract",
            "Did {claimant} have a statutory right to cancel the contract, and was it validly exercised?",
            (r"cooling[- ]off", r"cancel\w* within 14 days", r"bought online", r"distance contract", r"doorstep|off-premises"),
            "cancellation period 14 days distance contract off-premises information requirements refund",
        ),
        Doctrine(
            "late_payment", "Late payment of commercial debts", "contract",
            "Is {claimant} entitled to statutory interest and compensation on a late-paid commercial debt?",
            (r"late payment", r"unpaid invoice\w*", r"overdue invoice\w*", r"statutory interest"),
            "late payment commercial debt statutory interest fixed sum compensation",
        ),
        # ------------------------------------------------- tort & personal injury
        Doctrine(
            "contributory_negligence", "Contributory negligence", "tort",
            "Should {claimant}'s damages be reduced for contributory negligence?",
            (r"seat ?belt", r"helmet", r"contributor\w* negligen\w*", r"own fault", r"partly to blame", r"\bdrunk\b"),
            "contributory negligence apportionment reduction of damages claimant's share in responsibility",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "limitation", "Limitation of actions", "tort",
            "Is {claimant}'s claim time-barred, and does any extension of the limitation period apply?",
            (r"time[- ]barred", r"limitation period", r"(three|six) years (ago|after)", r"date of knowledge", r"out of time"),
            "limitation period time bar six years contract three years personal injury date of knowledge discretion to disapply",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "product_liability", "Defective products (strict liability)", "tort",
            "Is {defendant} strictly liable for damage caused by a defective product?",
            (r"defective product", r"product liability", r"(exploded|caught fire|overheated)", r"producer|importer", r"manufacturing defect"),
            "product liability defect safety persons generally are entitled to expect producer importer development risks defence",
        ),
        Doctrine(
            "fatal_accidents", "Fatal accidents and bereavement claims", "tort",
            "Can the dependants of the deceased recover for loss of dependency and bereavement?",
            (r"died|death of|killed", r"dependan\w*", r"bereavement", r"widow\w*"),
            "fatal accident dependants loss of dependency bereavement damages",
        ),
        Doctrine(
            "defective_premises", "Defective dwellings", "tort",
            "Is {defendant} liable for work on a dwelling that left it unfit for habitation?",
            (r"defective premises", r"unfit for (human )?habitation", r"new[- ]build", r"cladding"),
            "dwelling fit for habitation work done in a workmanlike or professional manner proper materials landlord duty of care",
        ),
        Doctrine(
            "whiplash_tariff", "Whiplash injury tariff", "tort",
            "Is {claimant}'s damages award for a whiplash injury limited by the statutory tariff?",
            (r"whiplash", r"soft tissue injur\w*", r"road traffic accident|rta\b"),
            "whiplash injury tariff road traffic accident soft tissue duration medical report",
            claimant_wants="contra", defence=True,
        ),
        # ------------------------------------------------- landlord & tenant
        Doctrine(
            "repairing_obligations", "Landlord's repairing and fitness obligations", "property",
            "Did {defendant} breach the landlord's statutory obligation to keep the dwelling in repair and fit for human habitation?",
            (r"landlord", r"\btenant\w*", r"\bleak\w*", r"\bdamp\b|mould|mold", r"ceiling", r"disrepair", r"repair\w*"),
            "landlord covenant to repair structure and exterior installations notice of disrepair fitness for human habitation tenancy",
        ),
        Doctrine(
            "tenancy_deposit", "Tenancy deposit protection", "property",
            "Did {defendant} protect {claimant}'s deposit and give the prescribed information, and what sanction follows if not?",
            (r"\bdeposit\b", r"deposit (protection|scheme)", r"prescribed information", r"assured shorthold"),
            "tenancy deposit protection scheme prescribed information 30 days sanction one to three times the deposit",
        ),
        Doctrine(
            "possession_eviction", "Possession, eviction and harassment", "property",
            "Is {defendant} entitled to possession, and was the eviction lawful?",
            (r"evict\w*", r"possession", r"notice to quit", r"section (8|21)", r"changed the locks", r"harass\w*", r"rent arrears"),
            "possession grounds assured tenancy notice court order unlawful eviction harassment rent arrears",
        ),
        Doctrine(
            "tenant_fees", "Prohibited tenant fees", "property",
            "Was the payment {defendant} required from {claimant} a prohibited payment under the Tenant Fees Act 2019?",
            (r"tenant fee\w*", r"admin(istration)? fee", r"referencing fee", r"holding deposit"),
            "prohibited payment permitted payment holding deposit tenant fees letting agent",
        ),
        Doctrine(
            "business_tenancy", "Business tenancy security of tenure", "property",
            "Does the business tenancy have security of tenure, and can the landlord oppose a new lease?",
            (r"business tenancy", r"commercial lease", r"(shop|office|unit) lease", r"new lease", r"contracted out"),
            "business tenancy security of tenure section 25 notice grounds of opposition new tenancy contracted out",
        ),
        # ------------------------------------------------- land: title, boundaries, possession (any jurisdiction)
        Doctrine(
            "title_possession", "Title and recovery of possession", "property",
            "Does {claimant} hold title to the disputed land, and is {claimant} entitled to recover possession of it from {defendant}?",
            (r"sale deed|title deed|conveyance|registered (title|deed)", r"recover(y of)? possession", r"\bmutation\b",
             r"\btitle\b", r"\bin possession\b|\bpossession of the (land|strip|property)\b"),
            "title ownership recovery of possession immovable property declaration of title suit for possession",
        ),
        Doctrine(
            "boundary_encroachment", "Boundary dispute and encroachment", "property",
            "Has {defendant} encroached on {claimant}'s land beyond the true boundary, and how is the boundary proved?",
            (r"encroach\w*", r"\bboundar(y|ies)\b", r"demarcation", r"\bsurvey\w*", r"\b(wall|fence|shed) (on|over|across)\b",
             r"\b(strip|marlas?|kanals?)\b"),
            "boundary demarcation encroachment survey removal of structure mandatory injunction",
        ),
        Doctrine(
            "adverse_possession", "Adverse possession and limitation", "property",
            "Has {defendant} acquired title to the disputed land by adverse possession, or is {claimant}'s claim to it time-barred?",
            (r"adverse possession", r"continuous(ly)? (and open )?possession", r"\bhostile\b", r"twelve years|12 years",
             r"time[- ]barred"),
            "adverse possession limitation twelve years possession open hostile continuous dispossession",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "injunction_relief", "Injunctions", "property",
            "Is {claimant} entitled to an injunction restraining {defendant}, or requiring removal of what was built?",
            (r"\binjunction\b", r"\brestrain\w*\b", r"remove (the )?(wall|shed|structure)", r"stop (him|her|them) from"),
            "perpetual injunction mandatory injunction restrain interference removal of construction",
        ),
        # ------------------------------------------------- employment
        Doctrine(
            "unfair_dismissal", "Unfair dismissal", "employment",
            "Was {claimant} unfairly dismissed: was there a potentially fair reason and a fair procedure?",
            (r"dismiss\w*", r"sacked|fired", r"disciplinary", r"gross misconduct", r"constructive", r"employment tribunal"),
            "unfair dismissal potentially fair reason conduct capability band of reasonable responses procedure qualifying period",
        ),
        Doctrine(
            "redundancy", "Redundancy", "employment",
            "Was {claimant}'s dismissal genuinely by reason of redundancy, with fair selection and consultation?",
            (r"redundan\w*", r"selection (criteria|pool)", r"restructur\w*", r"role (was )?(removed|deleted)"),
            "redundancy requirements for employees to carry out work of a particular kind ceased or diminished selection consultation redundancy payment",
        ),
        Doctrine(
            "wages_deductions", "Unlawful deductions and minimum wage", "employment",
            "Did {defendant} make an unauthorised deduction from {claimant}'s wages or pay below the minimum wage?",
            (r"deduct\w*", r"unpaid wages", r"minimum wage", r"holiday pay", r"payslip\w*"),
            "unauthorised deduction from wages written consent national minimum wage arrears",
        ),
        Doctrine(
            "discrimination", "Discrimination and harassment at work", "employment",
            "Did {defendant} discriminate against or harass {claimant} because of a protected characteristic?",
            (r"discriminat\w*", r"pregnan\w*", r"disabilit\w*|disabled", r"\brace\b|racial", r"\bsex\b|gender", r"religio\w*", r"harass\w*", r"reasonable adjustments?"),
            "direct discrimination indirect discrimination protected characteristic less favourable treatment harassment reasonable adjustments burden of proof",
        ),
        Doctrine(
            "whistleblowing", "Whistleblowing (protected disclosures)", "employment",
            "Did {claimant} make a protected disclosure, and was the detriment or dismissal because of it?",
            (r"whistleblow\w*", r"protected disclosure", r"reported .{0,40}(safety|fraud|breach)", r"raised concerns"),
            "protected disclosure qualifying disclosure public interest detriment automatically unfair dismissal",
        ),
        Doctrine(
            "working_time", "Working time and holidays", "employment",
            "Did {defendant} breach {claimant}'s rights to rest breaks, maximum hours or paid annual leave?",
            (r"working time", r"48[- ]hour", r"rest break\w*", r"annual leave", r"night work\w*"),
            "working time maximum weekly working time rest breaks annual leave holiday pay",
        ),
        Doctrine(
            "employment_status", "Employment status", "employment",
            "Was {claimant} an employee or worker rather than self-employed?",
            (r"self[- ]employed", r"\bgig\b", r"zero[- ]hours?", r"contractor", r"worker status"),
            "employee worker contract of service personal performance mutuality of obligation control",
        ),
        Doctrine(
            "collective_consultation", "Collective redundancy consultation", "employment",
            "Did {defendant} fail to consult collectively about proposed redundancies, entitling the employees to a protective award?",
            (r"20 or more", r"collective consultation", r"protective award", r"mass redundanc\w*"),
            "collective redundancy consultation 20 or more employees appropriate representatives protective award",
        ),
    ]
}


def score_doctrines(text: str) -> dict[str, int]:
    """Count the distinct cue patterns of each doctrine that occur in `text`."""
    low = text.lower()
    scores: dict[str, int] = {}
    for key, d in DOCTRINES.items():
        hits = sum(1 for p in d.patterns if re.search(p, low))
        if hits:
            scores[key] = hits
    return scores


def detect_doctrines(text: str, max_issues: int = 3, min_score: int = 2) -> list[tuple[str, int]]:
    """Rank the doctrines a fact sheet most likely raises (deterministic baseline)."""
    scores = score_doctrines(text)
    ranked = sorted(((k, s) for k, s in scores.items() if s >= min_score), key=lambda kv: (-kv[1], kv[0]))
    chosen = [k for k, _ in ranked]
    # Drop generic doctrines subsumed by a more specific one that was also detected.
    for k in list(chosen):
        for sub in DOCTRINES[k].subsumes:
            if sub in chosen:
                chosen.remove(sub)
    return [(k, scores[k]) for k in chosen[:max_issues]]


def opposite(position: str) -> str:
    return {"pro": "contra", "contra": "pro"}.get(position, position)
