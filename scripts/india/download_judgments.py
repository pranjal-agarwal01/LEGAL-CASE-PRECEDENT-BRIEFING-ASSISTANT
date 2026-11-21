"""Download the English PDFs listed in a selection file from the Indian Supreme Court open dataset.

Files come from the public S3 bucket (no account needed) and are saved as <out>/<year>/<path>_EN.pdf.
Already downloaded files are skipped, so the script can be re-run after an interruption.

    python scripts/india/download_judgments.py var/india/selection.json --out var/india/pdf
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/data/pdf"


def fetch(item: dict, out: Path) -> tuple[str, str]:
    year, path = item["year"], item["path"]
    dest = out / str(year) / f"{path}_EN.pdf"
    if dest.exists() and dest.stat().st_size > 0:
        return path, "skipped"
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}/year={year}/english/{path}_EN.pdf"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return path, "ok"
        except Exception as e:  # noqa: BLE001 - retried, then reported
            err = str(e)
            time.sleep(2 * (attempt + 1))
    return path, f"failed: {err}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("selection", type=Path)
    ap.add_argument("--out", type=Path, default=Path("var/india/pdf"))
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    items = json.loads(a.selection.read_text(encoding="utf-8"))["judgments"]
    counts: dict[str, int] = {}
    failed = []
    with ThreadPoolExecutor(a.workers) as pool:
        for i, (path, status) in enumerate(pool.map(lambda it: fetch(it, a.out), items), 1):
            key = status.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
            if key == "failed":
                failed.append((path, status))
            if i % 100 == 0:
                print(f"{i}/{len(items)} {counts}", flush=True)
    print(f"done {counts}")
    for path, status in failed[:20]:
        print(path, status, file=sys.stderr)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
