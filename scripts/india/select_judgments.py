"""Pick Supreme Court of India judgments on property and land disputes from the open dataset's metadata.

Source: Indian Supreme Court Judgments (AWS Open Data, CC-BY-4.0),
https://registry.opendata.aws/indian-supreme-court-judgments/

Reads metadata/parquet files (download them first, see README) and writes a selection JSON listing
each judgment's PDF path, citation, date, case number and the "Issue for Consideration" text.
Only civil matters are kept; land acquisition compensation cases are left out unless --with-acquisition.

    python scripts/india/select_judgments.py var/india/metadata --from 2010 --to 2025 \
        --out var/india/selection.json
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

# Words that mark a private property or land dispute. Each match adds to the score.
STRONG = [
    r"transfer of property act", r"specific relief act", r"specific performance", r"agreement (to|for) sale",
    r"agreement to sell", r"sale deed", r"gift deed", r"adverse possession", r"suit for (declaration|possession)",
    r"declaration of title", r"\btitle (to|over|of) the (suit )?(land|property|premises)", r"partition",
    r"easement", r"mortgage", r"redemption", r"\blease\b", r"lessee", r"\btenan(t|cy|ts)\b", r"eviction",
    r"rent control", r"landlord", r"pre-?emption", r"co-?sharer", r"encroach", r"mutation", r"revenue record",
    r"jamabandi", r"khasra", r"benami", r"registration act", r"injunction .{0,40}(land|property|possession)",
    r"immovable property", r"suit (land|property|premises)", r"joint family property", r"coparcen",
]
WEAK = [r"\bland\b", r"\bproperty\b", r"\bpossession\b", r"\bplot\b", r"\bpremises\b", r"\bowner(ship)?\b"]
ACQUISITION = [r"land acquisition", r"acquisition act", r"compensation for (the )?acquired", r"right to fair compensation"]
CRIMINAL = re.compile(r"criminal appeal|special leave petition ?\(crl|\(crl\.?\)|\bcrl\.?\b|writ petition ?\(criminal", re.I)


def clean(raw: str | None) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def issue_text(row: dict) -> str:
    """The editorial 'Issue for Consideration' and headnotes, without the site's disclaimer."""
    text = clean(row.get("raw_html")) or clean(row.get("description"))
    i = text.find("Issue for Consideration")
    if i < 0:  # older reports: the headnote follows the site's disclaimer and the case title
        k = text.find("carrying out the corrections.")
        i = k + len("carrying out the corrections.") if k >= 0 else 0
    text = text[i:]
    j = text.find("Decision Date :")
    return text[: j if j > 0 else None].strip()


def case_number(row: dict) -> str:
    m = re.search(r"Case No\s*:\s*(.+?)\s*\|", clean(row.get("raw_html")))
    return m.group(1).strip() if m else ""


def score(text: str) -> tuple[int, list[str]]:
    low = text.lower()
    hits = [p for p in STRONG if re.search(p, low)]
    weak = sum(1 for p in WEAK if re.search(p, low))
    return (3 * len(hits) + weak if hits else 0), hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("metadata_dir", type=Path)
    ap.add_argument("--from", dest="start", type=int, default=2010)
    ap.add_argument("--to", dest="end", type=int, default=2025)
    ap.add_argument("--min-score", type=int, default=4)
    ap.add_argument("--with-acquisition", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("var/india/selection.json"))
    a = ap.parse_args(argv)

    chosen, seen = [], 0
    for year in range(a.start, a.end + 1):
        f = a.metadata_dir / f"meta_{year}.parquet"
        if not f.exists():
            print(f"missing {f}", file=sys.stderr)
            continue
        for row in pq.read_table(f).to_pylist():
            seen += 1
            case_no = case_number(row)
            if CRIMINAL.search(case_no) or CRIMINAL.search(row.get("title") or ""):
                continue
            issue = issue_text(row)
            if not a.with_acquisition and any(re.search(p, issue.lower()) for p in ACQUISITION):
                continue
            s, hits = score(f"{row.get('title', '')} {issue}")
            if s < a.min_score:
                continue
            chosen.append({
                "year": year, "path": row["path"], "title": row.get("title") or "",
                "citation": row.get("citation") or "", "neutral_citation": row.get("case_id") or "",
                "date": row.get("decision_date") or "", "case_no": case_no, "judges": row.get("judge") or "",
                "author": row.get("author_judge") or "", "issue": issue[:4000], "score": s, "matched": hits,
            })
    chosen.sort(key=lambda r: (-r["year"], -r["score"]))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"_meta": {
        "source": "Indian Supreme Court Judgments, AWS Open Data Registry",
        "url": "https://registry.opendata.aws/indian-supreme-court-judgments/", "licence": "CC-BY-4.0",
        "years": [a.start, a.end], "screened": seen}, "judgments": chosen}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    by_year: dict[int, int] = {}
    for r in chosen:
        by_year[r["year"]] = by_year.get(r["year"], 0) + 1
    print(f"screened {seen}, chose {len(chosen)}: {by_year}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
