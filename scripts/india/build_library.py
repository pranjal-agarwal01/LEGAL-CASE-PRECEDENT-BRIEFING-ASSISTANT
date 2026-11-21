"""Build Precedent's Indian library file from Supreme Court judgment PDFs (and optional Act PDFs).

Each judgment is split into the court's numbered paragraphs (or ~200-word parts when the report has no
paragraph numbers). The editorial headnote is kept apart and labelled "Headnote", so it is never cited
as the court's own words. Passages are embedded with the configured embedding model (vectors are cached
in var/india/embeddings.npz, so a re-run only embeds what changed) and written to one gzip file that the
app loads into an empty database (see LIBRARY_SEED_URL).

    python scripts/india/build_library.py --selection var/india/selection.json --pdf-dir var/india/pdf \
        [--acts-dir var/india/acts] --out var/india/precedent-india-library.jsonl.gz [--no-embed] [--limit 50]

Authority ids are stable across rebuilds: J + the last two digits of the year + the INSC number
(2025 INSC 1286 -> J251286); Acts are L01, L02 ... in the order of ACTS below.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from legal_brief.config import Settings  # noqa: E402
from legal_brief.corpus import Judgment, Passage  # noqa: E402
from legal_brief.doctrines import score_doctrines  # noqa: E402
from legal_brief.ingest import _split_words, extract_text, regex_metadata, split_judgment, split_legislation  # noqa: E402
from legal_brief.web.store import doc_text, write_seed  # noqa: E402

log = logging.getLogger("build_library")
S3 = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/data/pdf"
SOURCE_NOTE = ("Supreme Court of India judgment from the Indian Supreme Court Judgments open dataset (eCourts, "
               "CC-BY-4.0). Check it against the official report before relying on it.")

# Acts read from --acts-dir, matched by file name (any PDF whose name contains the key). Order fixes the ids.
ACTS = [
    ("transfer of property", "Transfer of Property Act, 1882"),
    ("specific relief", "Specific Relief Act, 1963"),
    ("limitation", "Limitation Act, 1963"),
    ("registration", "Registration Act, 1908"),
    ("civil procedure", "Code of Civil Procedure, 1908"),
    ("contract", "Indian Contract Act, 1872"),
    ("evidence", "Indian Evidence Act, 1872"),
    ("sakshya", "Bharatiya Sakshya Adhiniyam, 2023"),
    ("hindu succession", "Hindu Succession Act, 1956"),
    ("easements", "Indian Easements Act, 1882"),
    ("stamp", "Indian Stamp Act, 1899"),
    ("benami", "Prohibition of Benami Property Transactions Act, 1988"),
    ("succession act", "Indian Succession Act, 1925"),
    ("punjab land revenue", "Punjab Land Revenue Act, 1887"),
    ("pre-emption", "Punjab Pre-emption Act, 1913"),
]

# ------------------------------------------------------------------------------------------- cleaning
_MARGIN_LINE = re.compile(r"(?m)^\s*(?:[A-H](?:\s*\|?\s*[A-H])*|[a-h])\s*$")
_MARGIN_END = re.compile(r"(?m)\s+[A-H]\s*$")
_RUNNING_HEAD = re.compile(r"(?m)^\s*(?:\d{1,4}\s+SUPREME COURT REPORTS.*|.*SUPREME COURT REPORTS\s*\[\d{4}\].*|"
                           r".{3,160}\[[A-Z][A-Za-z .,]+J(?:J)?\.?\]\s*\d{1,4}\s*|\d{1,4}\s*)$")
_JUDGMENT_START = re.compile(
    r"(?m)^\s*(?:Judgment\s*/\s*Order of the Supreme Court|The Judgment of the Court was delivered by|"
    r"J\s*U\s*D\s*G\s*M\s*E\s*N\s*T|JUDGMENT|O\s*R\s*D\s*E\s*R)\b")
_COUNSEL = re.compile(r"(?m)^\s*(?:CIVIL APPELLATE JURISDICTION|Appearances for Parties|Case Arising From)\b")


def _drop_page_headers(text: str) -> str:
    """Remove the report's running page headers: "[2024] 9 S.C.R. 953" lines, and any short line (usually
    the case name, "X v. Y") that repeats on three or more pages. The first line, the report's own
    citation, is kept."""
    lines = text.split("\n")
    counts: dict[str, int] = {}
    for l in lines:
        k = l.strip()
        if 0 < len(k) < 200:
            counts[k] = counts.get(k, 0) + 1
    out = []
    for i, l in enumerate(lines):
        k = l.strip()
        if i > 0 and re.fullmatch(r"\[\d{4}\]\s*\d+\s*S\.\s?C\.\s?R\.\s*\d+(?:\s+.{0,160})?", k):
            continue  # "[2024] 9 S.C.R. 953" (optionally followed by the case name) at a page break
        if i > 3 and counts.get(k, 0) >= 3 and re.search(r"\bv(?:s)?\.?\s", k) and len(k) < 160:
            continue
        out.append(l)
    return "\n".join(out)


def clean_text(text: str) -> str:
    text = text.replace("­", "")
    text = _drop_page_headers(text)
    text = _RUNNING_HEAD.sub("", text)
    text = _MARGIN_LINE.sub("", text)
    text = _MARGIN_END.sub("", text)
    text = re.sub(r"(?m)^.*\.{6,}.*$", "", text)  # contents lines with dot leaders
    # margin letters (B-H, and A after a lower-case word) printed in the middle of a sentence
    text = re.sub(r"(?<=[a-z,;)])[ \t][B-H][ \t](?=[a-z(])", " ", text)
    text = re.sub(r"(?<=[a-z,;])[ \t]A[ \t](?=[a-z])", " ", text)
    text = re.sub(r"(?m)^[ \t]*[A-H][ \t]+(?=\d{1,3}\.[ \t]|[a-z])", "", text)  # at the start of a line
    # the author's name runs into paragraph 1 ("DESAI, J. 1. This appeal"): start it on its own line
    text = re.sub(r"(\bJ\.|\bCJI?\.)[ \t]+(1\.[ \t]+[A-Z])", r"\1\n\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_headnote(text: str) -> tuple[str, str]:
    """(editorial headnote, the judgment itself). The headnote ends where the counsel list or judgment begins."""
    limit = int(len(text) * 0.6)
    m = None
    for cand in _JUDGMENT_START.finditer(text, 0, limit):
        m = cand
        if cand.group(0).strip().lower().startswith("judgment /"):
            break  # newer reports: "Judgment / Order of the Supreme Court" is the definite start
    if not m:
        return "", text
    head = text[: m.start()]
    c = _COUNSEL.search(head)
    if c:
        head = head[: c.start()]
    body = text[m.end():]
    body = re.sub(r"^\s*(?:Judgment|delivered by)?\s*", "", body)
    return head.strip(), body.strip()


def case_name(text: str, meta_title: str) -> str:
    """Name from the report's own heading (proper case), else the dataset title."""
    lines = [l.strip() for l in text[:1500].splitlines() if l.strip()]
    for i, l in enumerate(lines[:12]):
        if re.fullmatch(r"v(?:s)?\.?", l, re.I) and 0 < i < len(lines) - 1:
            first, second = lines[i - 1], lines[i + 1]
            if not first.isupper() and len(first) < 150 and len(second) < 150:
                return re.sub(r"\s+", " ", f"{first} v {second}").strip(" .")
    t = re.sub(r"\s+versus\s+", " v ", meta_title.strip(), flags=re.I)
    parts = [_title_case(x) for x in t.split(" v ", 1)]
    return " v ".join(x[:1].upper() + x[1:] for x in parts)


_SMALL = {"of", "and", "the", "by", "through", "thr", "for", "in", "at", "v"}


def _title_case(s: str) -> str:
    out = []
    for w in s.split():
        lw = w.lower()
        if lw in _SMALL:
            out.append(lw)
        elif re.fullmatch(r"(?:[A-Z]\.)+[A-Z]?\.?", w) or lw in {"ors.", "anr.", "ors", "anr", "lrs.", "lrs", "(d)"}:
            out.append(w if "." in w and len(w) <= 6 and w.isupper() and lw not in {"ors.", "anr.", "lrs."} else w.capitalize())
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def iso_date(d: str) -> str:
    try:
        return datetime.strptime(d, "%d-%m-%Y").date().isoformat()
    except ValueError:
        return ""


def judgment_id(neutral: str, year: int, path: str) -> str:
    m = re.search(r"(\d{4})\s*INSC\s*(\d{1,4})", neutral or "")
    if m:
        return f"J{m.group(1)[2:]}{int(m.group(2)):04d}"
    nums = re.findall(r"\d+", path)  # no neutral citation: year + SCR volume/page (still unique)
    return f"J{str(year)[2:]}{int(nums[1]) % 10:01d}{int(nums[2]) % 1000:03d}"


def build_judgment(item: dict, pdf: Path) -> Judgment | None:
    raw = extract_text(pdf.name, pdf.read_bytes())
    text = clean_text(raw)
    if len(text.split()) < 300:
        return None
    head, body = split_headnote(text)
    paras = split_judgment(body)
    if paras and paras[0].pid == "p0":
        head = f"{head}\n{paras[0].text}".strip() if len(paras[0].text.split()) > 30 else head
        paras = paras[1:]
    jid = judgment_id(item.get("neutral_citation", ""), item["year"], item["path"])
    passages = []
    for i, piece in enumerate(_split_words(re.sub(r"\s*\n\s*", " ", head), 220) if head else [], 1):
        passages.append(Passage(jid, f"h{i}", "headnote", piece, label=f"Headnote (part {i})"))
    for p in paras:
        if len(p.text.split()) < 4:
            continue
        passages.append(Passage(jid, p.pid, "paragraph", p.text, label=p.label))
    if len([p for p in passages if p.section == "paragraph"]) < 3:
        return None
    neutral = item.get("neutral_citation", "")
    neutral = re.sub(r"(\d{4})\s*INSC\s*(\d+)", r"\1 INSC \2", neutral)
    citation = "; ".join(c for c in (neutral, item.get("citation", "")) if c)
    scores = score_doctrines(f"{item.get('issue', '')}\n{head}\n{body[:20000]}")
    doctrines = {k: "mixed" for k, s in sorted(scores.items(), key=lambda kv: -kv[1])[:4] if s >= 2}
    issue = re.sub(r"^Issue for Consideration\s*", "", item.get("issue", "")).strip()
    return Judgment(jid, case_name(raw, item.get("title", "")), citation, "Supreme Court of India", item["year"],
                    "property", doctrines, tuple(passages), kind="judgment",
                    url=f"{S3}/year={item['year']}/english/{item['path']}_EN.pdf", date=iso_date(item.get("date", "")),
                    summary=issue[:700], source_note=SOURCE_NOTE, jurisdiction="India")


def build_act(pdf: Path, aid: str, title: str) -> Judgment | None:
    raw = extract_text(pdf.name, pdf.read_bytes())
    paras = split_legislation(raw)
    if len(paras) < 5:
        log.warning("%s: only %d provisions found, skipped", pdf.name, len(paras))
        return None
    year = int(re.search(r"(\d{4})\s*$", title).group(1))
    passages = tuple(Passage(aid, p.pid, "provision", p.text, label=p.label) for p in paras)
    meta = regex_metadata(raw, pdf.name)
    return Judgment(aid, title, "", "Parliament of India" if "Punjab" not in title else "Punjab Legislature", year,
                    "property", meta.doctrines, passages, kind="legislation", url="", date="",
                    source_note="India Code (Legislative Department). Check the current text on indiacode.nic.in.",
                    jurisdiction="India")


# ------------------------------------------------------------------------------------------- reading
def _read_one(args: tuple[dict, Path]) -> Judgment | None:
    item, pdf_dir = args
    pdf = pdf_dir / str(item["year"]) / f"{item['path']}_EN.pdf"
    try:
        return build_judgment(item, pdf) if pdf.exists() else None
    except Exception as e:  # noqa: BLE001 - one unreadable report must not stop the build
        log.warning("%s: %s", pdf.name, e)
        return None


def read_judgments(items: list[dict], pdf_dir: Path) -> list[Judgment]:
    """Parse the PDFs in parallel processes (pypdf is slow), keeping the selection's order."""
    from concurrent.futures import ProcessPoolExecutor

    out, seen = [], set()
    with ProcessPoolExecutor() as pool:
        for i, j in enumerate(pool.map(_read_one, [(it, pdf_dir) for it in items], chunksize=8), 1):
            if j is not None and j.id not in seen:
                seen.add(j.id)
                out.append(j)
            if i % 200 == 0:
                log.info("%d/%d judgments read", i, len(items))
    log.info("%d judgments usable, %d skipped", len(out), len(items) - len(out))
    return out


# ------------------------------------------------------------------------------------------- embedding
class _BatchedCache:
    """FileCache that writes to disk only when asked (FileCache rewrites the whole file on every put)."""

    def __init__(self, path: Path):
        from legal_brief.embeddings import FileCache

        self.file = FileCache(path)
        self.lock = __import__("threading").Lock()

    def get_many(self, keys):
        return self.file.get_many(keys)

    def put_many(self, items):
        import numpy as np

        with self.lock:
            self.file._d.update({k: np.asarray(v, dtype=np.float16) for k, v in items.items()})

    def flush(self):
        with self.lock:
            self.file.put_many({})


def embed_all(authorities: list[Judgment], settings: Settings, workers: int) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    import legal_brief.embeddings as emb

    emb.BATCH = 256  # fewer, larger requests
    cache = _BatchedCache(ROOT / "var/india/embeddings.npz")
    embedder = emb.build_embedder(settings, cache)
    if embedder is None:
        raise SystemExit("No embedding model configured (EMBEDDING_MODEL in .env); use --no-embed.")
    embedder.client = embedder.client.with_options(max_retries=10)  # wait out rate limits
    started = time.perf_counter()
    vectors: dict = {}

    def one(j: Judgment):
        texts = [doc_text(j.name, j.kind, j.area, p.display, p.text) for p in j.passages]
        return j.id, embedder.embed(texts)

    with ThreadPoolExecutor(workers) as pool:
        for k, (jid, v) in enumerate(pool.map(one, authorities), 1):
            vectors[jid] = v
            if k % 100 == 0:
                cache.flush()
                log.info("embedded %d/%d authorities (%.0fs)", k, len(authorities), time.perf_counter() - started)
    cache.flush()
    return vectors


# ------------------------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selection", type=Path, default=ROOT / "var/india/selection.json")
    ap.add_argument("--pdf-dir", type=Path, default=ROOT / "var/india/pdf")
    ap.add_argument("--acts-dir", type=Path, default=ROOT / "var/india/acts")
    ap.add_argument("--out", type=Path, default=ROOT / "var/india/precedent-india-library.jsonl.gz")
    ap.add_argument("--no-embed", action="store_true", help="write the file without vectors (keyword search only)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4, help="parallel embedding requests")
    ap.add_argument("--stances", type=Path, default=None,
                    help="JSON {authority id: {doctrine: pro|contra|mixed}} read from the holdings, replacing the tags")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "openai", "pypdf"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    authorities: list[Judgment] = []
    if a.acts_dir.exists():
        pdfs = sorted(a.acts_dir.glob("*.pdf"))
        for n, (key, title) in enumerate(ACTS, 1):
            match = next((p for p in pdfs if key in p.name.lower().replace("_", " ").replace("-", " ")), None)
            if match:
                act = build_act(match, f"L{n:02d}", title)
                if act:
                    authorities.append(act)
                    log.info("act %s: %d provisions", title, len(act.passages))

    items = json.loads(a.selection.read_text(encoding="utf-8"))["judgments"]
    if a.limit:
        items = items[: a.limit]
    authorities += read_judgments(items, a.pdf_dir)
    if a.stances:
        from dataclasses import replace

        stances = json.loads(a.stances.read_text(encoding="utf-8"))
        authorities = [replace(j, doctrines=stances[j.id]) if j.id in stances else j for j in authorities]
    n_pass = sum(len(j.passages) for j in authorities)
    log.info("%d authorities, %d passages", len(authorities), n_pass)

    settings = Settings.from_env()
    vectors: dict[str, object] = {}
    if not a.no_embed:
        vectors = embed_all(authorities, settings, a.workers)

    meta = {"source": "Supreme Court of India judgments on property and land, 2005-2025 (Indian Supreme Court "
                      "Judgments open dataset, CC-BY-4.0)",
            "built": date.today().isoformat(), "authorities": len(authorities), "passages": n_pass,
            "embedding_model": "" if a.no_embed else settings.embedding_model}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    n = write_seed(a.out, ((j, vectors.get(j.id)) for j in authorities), settings.embedding_dims, meta)
    log.info("wrote %s: %d authorities, %.1f MB", a.out, n, a.out.stat().st_size / 1e6)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
