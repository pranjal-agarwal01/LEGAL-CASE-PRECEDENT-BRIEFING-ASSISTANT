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


@dataclass(frozen=True)
class Doctrine:
    key: str
    label: str
    area: str  # "tort" or "contract"
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
