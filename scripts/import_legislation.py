"""Import the statutes the product covers into data/library/legislation.json.

Source: legislation.gov.uk data (Open Government Licence v3.0), read through the
government's Lex API (https://lex.lab.i.ai.gov.uk), which serves the same revised
text as JSON. legislation.gov.uk itself blocks automated clients behind a bot
challenge, so this script uses Lex for a one-off snapshot; it is not called at
runtime. Re-run it to refresh the snapshot:

    python scripts/import_legislation.py

Only provisions that extend to England are kept, long provisions are split into
parts of about 350 words, and repealed or empty provisions are skipped.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

LEX = "https://lex.lab.i.ai.gov.uk"
OUT = Path(__file__).resolve().parents[1] / "data" / "library" / "legislation.json"
UA = "legal-brief-importer/1.0"
MAX_WORDS = 350
EXTENDS_TO_ENGLAND = {"England", "England and Wales", "Great Britain", "United Kingdom", "E+W", "E+W+S", "E+W+S+N.I."}


def rng(a: int, b: int) -> list[str]:
    return [str(n) for n in range(a, b + 1)]


# (legislation id, practice areas, doctrine tags, provisions to keep (None = all sections), schedules to keep)
ACTS: list[tuple[str, list[str], dict[str, str], list[str] | None, list[str]]] = [
    # ---------------------------------------------------------------- contract & consumer
    ("ukpga/2015/15", ["contract"], {"consumer_goods_rights": "pro", "consumer_services_rights": "pro",
                                     "unfair_terms": "pro", "exclusion_clause": "contra"},
     rng(1, 76), ["2"]),
    ("ukpga/1977/50", ["contract"], {"exclusion_clause": "contra", "unfair_terms": "pro"}, rng(1, 14), ["2"]),
    ("ukpga/1967/7", ["contract"], {"misrepresentation": "pro"}, None, []),
    ("ukpga/1979/54", ["contract"], {"implied_terms_business": "pro"}, None, []),
    ("ukpga/1982/29", ["contract"], {"implied_terms_business": "pro", "consumer_services_rights": "pro"}, None, []),
    ("ukpga/1999/31", ["contract"], {"third_party_rights": "pro"}, None, []),
    ("ukpga/Geo6/6-7/40", ["contract"], {"frustration": "mixed"}, None, []),
    ("ukpga/1998/20", ["contract"], {"late_payment": "pro"}, None, []),
    ("uksi/2013/3134", ["contract"], {"consumer_cancellation": "pro"}, None, []),
    # ---------------------------------------------------------------- tort & personal injury
    ("ukpga/Eliz2/5-6/31", ["tort"], {"occupiers_liability": "mixed"}, None, []),
    ("ukpga/1984/3", ["tort"], {"occupiers_liability": "mixed"}, None, []),
    ("ukpga/Geo6/8-9/28", ["tort"], {"contributory_negligence": "contra"}, None, []),
    ("ukpga/1980/58", ["tort", "contract"], {"limitation": "contra"}, None, []),
    ("ukpga/2006/29", ["tort"], {"standard_of_care": "contra", "causation": "pro"}, None, []),
    ("ukpga/2015/3", ["tort"], {"standard_of_care": "contra"}, None, []),
    ("ukpga/1987/43", ["tort"], {"product_liability": "pro"}, rng(1, 9) + ["45", "46"], []),
    ("ukpga/1976/30", ["tort"], {"fatal_accidents": "pro"}, None, []),
    ("ukpga/1972/35", ["tort", "property"], {"defective_premises": "pro", "repairing_obligations": "pro"}, None, []),
    ("ukpga/1971/22", ["tort"], {"strict_liability": "pro"}, None, []),
    ("ukpga/2018/29", ["tort"], {"whiplash_tariff": "contra"}, None, []),
    # ---------------------------------------------------------------- landlord & tenant
    ("ukpga/1985/70", ["property"], {"repairing_obligations": "pro"}, None, []),
    ("ukpga/1988/50", ["property"], {"possession_eviction": "mixed"}, rng(1, 45), ["2"]),
    ("ukpga/2004/34", ["property"], {"tenancy_deposit": "pro"}, ["212", "212A", "213", "214", "215", "215A", "215B"], []),
    ("ukpga/1977/43", ["property"], {"possession_eviction": "pro"}, None, []),
    ("ukpga/2019/4", ["property"], {"tenant_fees": "pro"}, None, ["1"]),
    ("ukpga/Eliz2/2-3/56", ["property"], {"business_tenancy": "mixed"}, rng(23, 46), []),
    # ---------------------------------------------------------------- employment
    ("ukpga/1996/18", ["employment"], {"unfair_dismissal": "pro", "redundancy": "pro", "wages_deductions": "pro",
                                        "whistleblowing": "pro", "employment_status": "mixed"},
     rng(1, 27) + ["43A", "43B", "43C", "43G", "43H", "43K", "47B", "48", "49"] + rng(86, 93)
     + ["94", "95", "97", "98", "98A", "98B", "99", "100", "103A", "104", "108", "111", "112", "113", "114", "115",
        "116", "117", "118", "119", "120", "122", "123", "124", "135", "136", "139", "141", "155", "162", "163",
        "203", "230"], []),
    ("ukpga/2010/15", ["employment"], {"discrimination": "pro"},
     rng(4, 27) + rng(39, 41) + ["60", "64", "65", "66", "108", "109", "110", "120", "123", "124", "136", "212"], []),
    ("ukpga/1998/39", ["employment"], {"wages_deductions": "pro"}, rng(1, 3) + ["17", "54"], []),
    ("uksi/1998/1833", ["employment"], {"working_time": "pro"}, None, []),
    ("ukpga/1992/52", ["employment"], {"collective_consultation": "pro"}, rng(188, 192), []),
]


TITLES = {'ukpga/2015/15': ('Consumer Rights Act 2015', 2015),
          'ukpga/1977/50': ('Unfair Contract Terms Act 1977', 1977),
          'ukpga/1967/7': ('Misrepresentation Act 1967', 1967),
          'ukpga/1979/54': ('Sale of Goods Act 1979', 1979),
          'ukpga/1982/29': ('Supply of Goods and Services Act 1982', 1982),
          'ukpga/1999/31': ('Contracts (Rights of Third Parties) Act 1999', 1999),
          'ukpga/Geo6/6-7/40': ('Law Reform (Frustrated Contracts) Act 1943', 1943),
          'ukpga/1998/20': ('Late Payment of Commercial Debts (Interest) Act 1998', 1998),
          'uksi/2013/3134': ('Consumer Contracts (Information, Cancellation and Additional Charges) Regulations 2013', 2013),
          'ukpga/Eliz2/5-6/31': ("Occupiers' Liability Act 1957", 1957),
          'ukpga/1984/3': ("Occupiers' Liability Act 1984", 1984),
          'ukpga/Geo6/8-9/28': ('Law Reform (Contributory Negligence) Act 1945', 1945),
          'ukpga/1980/58': ('Limitation Act 1980', 1980),
          'ukpga/2006/29': ('Compensation Act 2006', 2006),
          'ukpga/2015/3': ('Social Action, Responsibility and Heroism Act 2015', 2015),
          'ukpga/1987/43': ('Consumer Protection Act 1987', 1987),
          'ukpga/1976/30': ('Fatal Accidents Act 1976', 1976),
          'ukpga/1972/35': ('Defective Premises Act 1972', 1972),
          'ukpga/1971/22': ('Animals Act 1971', 1971),
          'ukpga/2018/29': ('Civil Liability Act 2018', 2018),
          'ukpga/1985/70': ('Landlord and Tenant Act 1985', 1985),
          'ukpga/1988/50': ('Housing Act 1988', 1988),
          'ukpga/2004/34': ('Housing Act 2004', 2004),
          'ukpga/1977/43': ('Protection from Eviction Act 1977', 1977),
          'ukpga/2019/4': ('Tenant Fees Act 2019', 2019),
          'ukpga/Eliz2/2-3/56': ('Landlord and Tenant Act 1954', 1954),
          'ukpga/1996/18': ('Employment Rights Act 1996', 1996),
          'ukpga/2010/15': ('Equality Act 2010', 2010),
          'ukpga/1998/39': ('National Minimum Wage Act 1998', 1998),
          'uksi/1998/1833': ('Working Time Regulations 1998', 1998),
          'ukpga/1992/52': ('Trade Union and Labour Relations (Consolidation) Act 1992', 1992)}


def post(path: str, body: dict) -> object:
    req = urllib.request.Request(LEX + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - transient network or rate-limit errors
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1} after {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def provision_key(uri: str) -> tuple[str, str] | None:
    """('section', '11A') from .../section/11A; schedules, regulations and articles likewise."""
    m = re.search(r"/(section|schedule|regulation|article)/([0-9A-Za-z]+)$", uri)
    return (m.group(1), m.group(2)) if m else None


def clean(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"^(Section|Schedule|Regulation|Article) [0-9A-Za-z]+\)\s*", "", text.strip())
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def is_dead(text: str) -> bool:
    body = re.sub(r"[\W\d]+", " ", text).strip().lower()
    return len(body) < 40 or bool(re.fullmatch(r"(repealed|revoked|omitted)?\s*.{0,60}(repealed|revoked).{0,80}", body))


def split_long_line(line: str, max_words: int) -> list[str]:
    """Break one over-long line at sentence, semicolon or comma boundaries."""
    if len(line.split()) <= max_words:
        return [line]
    pieces = re.split(r"(?<=[.;])\s+|(?<=,)(?=\S)", line)
    out, cur = [], ""
    for p in pieces:
        if cur and len((cur + " " + p).split()) > max_words:
            out.append(cur.strip())
            cur = p
        else:
            cur = f"{cur} {p}" if cur else p
    if cur.strip():
        out.append(cur.strip())
    return out


def chunk(text: str, max_words: int = MAX_WORDS) -> list[str]:
    lines = [piece for ln in text.split("\n") for piece in split_long_line(ln, max_words)]
    parts, cur, n = [], [], 0
    for ln in lines:
        w = len(ln.split())
        if cur and n + w > max_words:
            parts.append("\n".join(cur))
            cur, n = [], 0
        cur.append(ln)
        n += w
    if cur:
        parts.append("\n".join(cur))
    return parts


PREFIX = {"section": ("s", "s "), "schedule": ("sch", "Sch "), "regulation": ("reg", "reg "), "article": ("art", "art ")}


def main() -> int:
    acts_out = []
    for n, (lid, areas, doctrines, keep, schedules) in enumerate(ACTS, 1):
        full_id = f"http://www.legislation.gov.uk/id/{lid}"
        title, year = TITLES[lid]
        parts = lid.split("/")
        info = {}
        if len(parts) == 3 and parts[1].isdigit():
            try:
                got = post("/legislation/lookup", {"legislation_type": parts[0], "year": int(parts[1]),
                                                   "number": int(parts[2])})
                info = got if isinstance(got, dict) and got.get("title") else {}
            except Exception as e:  # noqa: BLE001 - metadata is optional
                print(f"  no metadata for {lid}: {e}", file=sys.stderr)
            time.sleep(1.2)
        rows = post("/legislation/section/lookup", {"legislation_id": full_id, "limit": 2000})
        rows = rows if isinstance(rows, list) else rows.get("results", [])
        provisions = []
        for row in rows:
            key = provision_key(row.get("uri") or row.get("id", ""))
            if not key:
                continue
            kind, num = key
            if not any(e in EXTENDS_TO_ENGLAND for e in (row.get("extent") or ["England"])):
                continue
            if kind == "schedule":
                if num not in schedules:
                    continue
            elif keep is not None and num not in keep:
                continue
            text = clean(row.get("text") or "")
            if is_dead(text):
                continue
            pfx, label_pfx = PREFIX[kind]
            pieces = chunk(text)
            for k, piece in enumerate(pieces, 1):
                pid = f"{pfx}{num}" + (f".{k}" if len(pieces) > 1 else "")
                label = f"{label_pfx}{num}" + (f" (part {k} of {len(pieces)})" if len(pieces) > 1 else "")
                provisions.append({"pid": pid, "label": label, "title": (row.get("title") or "").strip(),
                                   "text": piece, "url": row.get("uri") or ""})

        def order(p: dict) -> tuple:
            m = re.match(r"([a-z]+)(\d+)([A-Z]*)(?:\.(\d+))?", p["pid"])
            kind_rank = {"s": 0, "reg": 0, "art": 0, "sch": 1}.get(m.group(1), 2)
            return (kind_rank, int(m.group(2)), m.group(3), int(m.group(4) or 0))

        provisions.sort(key=order)
        acts_out.append({
            "id": f"L{n:02d}", "legislation_id": lid, "title": title, "type": lid.split("/")[0], "year": year,
            "url": f"https://www.legislation.gov.uk/{lid}", "areas": areas, "doctrines": doctrines,
            "status": info.get("status", "revised"), "valid_date": info.get("valid_date"),
            "provisions": provisions,
        })
        print(f"L{n:02d} {title}: {len(provisions)} passages from {len(rows)} provisions")
        time.sleep(1.2)  # stay well inside Lex's 60 requests/minute limit

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "_meta": {
            "source": "legislation.gov.uk (revised text), via the Lex API of i.AI",
            "licence": "Contains public sector information licensed under the Open Government Licence v3.0.",
            "licence_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
            "imported": date.today().isoformat(),
            "jurisdiction": "England and Wales (provisions extending to England)",
            "note": "Revised text as held by legislation.gov.uk on the import date. Check legislation.gov.uk for "
                    "amendments not yet applied (outstanding effects) before relying on a provision.",
        },
        "acts": acts_out,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    total = sum(len(a["provisions"]) for a in acts_out)
    print(f"Wrote {OUT} ({len(acts_out)} instruments, {total} passages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
