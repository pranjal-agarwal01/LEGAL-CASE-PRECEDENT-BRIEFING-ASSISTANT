"""A small taxonomy of legal doctrines (issue types) used across the agents.

Each doctrine knows how to phrase its issue question, which words in a fact sheet
suggest it, which search terms help retrieval, and which answer the plaintiff
normally wants ('pro' = the doctrine applies / liability or enforceability is
established, 'contra' = it does not). Judgments in the corpus are tagged with the
same keys, which lets the debaters split retrieved precedents into supporting and
opposing authorities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


AREA_LABELS = {"property": "Property and land"}


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
            "specific_performance", "Specific performance of an agreement to sell", "property",
            "Is {claimant} entitled to specific performance of the agreement to sell the property?",
            (r"agreement (to|for) sell|agreement to sale|agreement for sale", r"specific performance", r"earnest money",
             r"\badvance\b", r"sale consideration", r"balance (amount|consideration)", r"execute (the )?sale deed"),
            "specific performance agreement to sell Specific Relief Act section 10 section 16 discretion execution of sale deed",
            subsumes=("title_declaration",),
        ),
        Doctrine(
            "readiness_willingness", "Readiness and willingness to perform", "property",
            "Was {claimant} continuously ready and willing to perform the agreement, as section 16(c) of the "
            "Specific Relief Act requires?",
            (r"ready and willing", r"readiness", r"balance (amount|consideration)", r"(did not|failed to) pay",
             r"deposit(ed)? (the )?balance", r"time (is|was) (of the )?essence"),
            "readiness and willingness section 16(c) Specific Relief Act continuous plaintiff conduct balance consideration",
            defence=True,
        ),
        Doctrine(
            "title_declaration", "Title and declaration of ownership", "property",
            "Has {claimant} proved title to the suit property so as to be entitled to a declaration of ownership "
            "and possession?",
            (r"\btitle\b", r"\bowner(ship)?\b", r"declaration", r"sale deed", r"registered (sale )?deed",
             r"suit (land|property)"),
            "declaration of title ownership suit for possession burden of proof sale deed section 34 Specific Relief Act",
        ),
        Doctrine(
            "revenue_entries", "Revenue entries and mutation", "property",
            "Do the revenue record entries (mutation, jamabandi, khasra) prove or confer title to the land?",
            (r"mutation", r"jamabandi", r"khasra|khatauni|khewat", r"revenue (record|entr)", r"patwari|tehsildar",
             r"girdawari|record of rights|fard"),
            "mutation entries revenue records do not confer title fiscal purpose presumption record of rights",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "adverse_possession", "Adverse possession", "property",
            "Has {defendant} acquired title by adverse possession that is open, hostile and continuous for the "
            "statutory period?",
            (r"adverse possession", r"hostile", r"(open|peaceful|uninterrupted|continuous) possession",
             r"in possession (since|for)", r"\b(12|twelve|30|thirty) years\b", r"possession of the (land|property)"),
            "adverse possession hostile animus open continuous twelve years Article 65 Limitation Act ouster",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "possession_injunction", "Possession and permanent injunction", "property",
            "Is {claimant} in settled possession and entitled to an injunction restraining {defendant} from "
            "interfering?",
            (r"injunction", r"dispossess\w*", r"settled possession", r"interfer\w*", r"forcibl\w*", r"trespass\w*",
             r"encroach\w*"),
            "permanent injunction settled possession dispossession interference section 38 Specific Relief Act trespass",
        ),
        Doctrine(
            "partition", "Partition and shares of co-owners", "property",
            "Is {claimant} entitled to partition and separate possession of a share in the property?",
            (r"partition", r"\bshare\b", r"co-?owner\w*", r"joint (family )?property", r"ancestral", r"\bhuf\b",
             r"family settlement"),
            "partition separate possession share co-owner joint family property family settlement preliminary decree",
            subsumes=("title_declaration",),
        ),
        Doctrine(
            "succession", "Succession and inheritance", "property",
            "Does {claimant} take a share in the property by succession, as a coparcener or legal heir?",
            (r"succession", r"coparcen\w*", r"legal heirs?", r"intestate", r"daughter", r"\bwill\b|testament\w*",
             r"inherit\w*"),
            "Hindu Succession Act section 6 coparcener daughter legal heirs intestate succession will probate",
            subsumes=("title_declaration",),
        ),
        Doctrine(
            "deed_cancellation", "Validity and cancellation of a deed", "property",
            "Is the sale or gift deed void or voidable, and should it be cancelled?",
            (r"cancel\w* (of )?(the )?(sale|gift|release) deed", r"forg(ed|ery)", r"fraud\w*", r"undue influence",
             r"without (any )?consideration", r"\bvoid\b", r"sham"),
            "cancellation of instrument section 31 Specific Relief Act void voidable fraud forgery undue influence",
        ),
        Doctrine(
            "limitation", "Limitation", "property",
            "Is the suit within the period of limitation under the Limitation Act, 1963?",
            (r"limitation", r"time[- ]barred|barred by (time|limitation)", r"\bdelay\b", r"condon\w*",
             r"article (54|58|59|64|65|113)", r"\byears? (after|later)\b"),
            "Limitation Act 1963 Article 54 Article 58 Article 59 Article 65 starting point knowledge time barred",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "part_performance", "Part performance (section 53A TPA)", "property",
            "Can {defendant} protect possession taken under the agreement as part performance under section 53A of "
            "the Transfer of Property Act?",
            (r"part performance", r"53-?a", r"possession (was )?(handed|delivered|given) .{0,40}agreement",
             r"in possession under (the|an) agreement"),
            "part performance section 53A Transfer of Property Act possession in furtherance of contract willing to perform",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "lis_pendens", "Transfer during a pending suit (lis pendens)", "property",
            "Is the transfer made while the suit was pending bound by the result of the suit under section 52 of the "
            "Transfer of Property Act?",
            (r"lis pendens", r"pendente lite", r"during the pendency|pendency of the suit",
             r"(while|when) the suit was pending|pending suit", r"subsequent (purchaser|transferee)",
             r"(sale deed|transfer|sold).{0,100}(pending|pendency)|(pending|pendency).{0,100}(sale deed|transfer|sold)"),
            "lis pendens section 52 Transfer of Property Act transferee pendente lite bound by decree",
            subsumes=("title_declaration",),
        ),
        Doctrine(
            "bona_fide_purchaser", "Bona fide purchaser without notice", "property",
            "Is the later purchaser protected as a transferee for value in good faith without notice of the earlier "
            "agreement?",
            (r"bona fide purchaser", r"without notice", r"good faith", r"ostensible owner", r"subsequent purchaser",
             r"paid (full )?value"),
            "bona fide purchaser for value without notice section 19(b) Specific Relief Act section 41 Transfer of Property Act ostensible owner",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "registration", "Registration and admissibility of documents", "property",
            "Is the unregistered or unstamped document admissible, and can it transfer any interest in the "
            "property?",
            (r"unregistered", r"registration", r"stamp duty|unstamped|insufficiently stamped",
             r"compulsorily registrable", r"notari[sz]ed", r"power of attorney"),
            "Registration Act 1908 section 17 section 49 unregistered document collateral purpose stamp duty GPA sale",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "benami", "Benami transactions", "property",
            "Is the property held benami, and is a claim to it barred by the Benami Transactions (Prohibition) Act?",
            (r"benami", r"in the name of (his|her) (wife|son|daughter|husband)", r"paid the (sale )?consideration",
             r"real owner", r"name-?lender"),
            "benami transaction source of consideration intention real owner Benami Transactions Prohibition Act",
            defence=True,
        ),
        Doctrine(
            "eviction", "Eviction of a tenant", "property",
            "Is {claimant} entitled to evict the tenant on a ground recognised by the applicable rent law?",
            (r"\btenan(t|cy|ts)\b", r"evict\w*", r"\brent\b", r"landlord", r"bona fide (requirement|need)",
             r"sub-?let\w*", r"arrears"),
            "eviction tenant rent control bona fide requirement arrears of rent subletting landlord tenant relationship",
            subsumes=("title_declaration",),
        ),
        Doctrine(
            "lease_termination", "Lease, notice to quit and holding over", "property",
            "Was the lease validly determined, for example by notice under section 106 of the Transfer of Property "
            "Act, and is the occupant holding over?",
            (r"notice to quit", r"section 106", r"\blease\b", r"lessee|lessor", r"holding over", r"month[- ]to[- ]month"),
            "lease determination notice to quit section 106 section 111 Transfer of Property Act holding over mesne profits",
            subsumes=("title_declaration",),
        ),
        Doctrine(
            "mortgage_redemption", "Mortgage and redemption", "property",
            "Is {claimant} entitled to redeem the mortgage, or has the right of redemption been lost?",
            (r"mortgag\w*", r"redeem|redemption", r"usufructuary", r"clog on (the )?(equity|redemption)",
             r"sale with (a )?condition"),
            "mortgage redemption section 60 Transfer of Property Act usufructuary mortgage clog on redemption conditional sale",
        ),
        Doctrine(
            "pre_emption", "Pre-emption", "property",
            "Does {claimant} have a right of pre-emption over the sale of the land?",
            (r"pre-?emption", r"co-?sharer", r"contiguous", r"haq shufa", r"right of first refusal"),
            "pre-emption co-sharer superior right Punjab Pre-emption Act sale of agricultural land",
        ),
        Doctrine(
            "easement", "Easements and rights of way", "property",
            "Does {claimant} have an easement, such as a right of way or of light and air, over {defendant}'s land?",
            (r"easement\w*", r"right of way", r"\bpassage\b|pathway", r"light and air", r"prescription",
             r"necessity"),
            "easement right of way prescription twenty years Indian Easements Act necessity dominant servient",
        ),
        Doctrine(
            "plaint_rejection", "Rejection of the plaint", "property",
            "Should the plaint be rejected under Order VII Rule 11 CPC because it discloses no cause of action or "
            "the suit is barred by law?",
            (r"order (vii|7) rule 11", r"reject(ion of)? the plaint", r"no cause of action", r"barred by (any )?law",
             r"clever drafting"),
            "Order VII Rule 11 rejection of plaint cause of action barred by law averments in the plaint",
            claimant_wants="contra", defence=True,
        ),
        Doctrine(
            "res_judicata", "Res judicata and earlier suits", "property",
            "Is the suit barred by res judicata or by Order II Rule 2 CPC because of an earlier suit?",
            (r"res judicata", r"(earlier|previous|former) suit", r"order (ii|2) rule 2", r"same cause of action",
             r"constructive res judicata"),
            "res judicata section 11 CPC Order II Rule 2 earlier suit same cause of action finality",
            claimant_wants="contra", defence=True,
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
