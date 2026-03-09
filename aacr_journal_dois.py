"""
Export DOIs for publications in AACR journals via the Crossref REST API.

AACR (American Association for Cancer Research) Crossref member ID: 1086

This script uses cursor-based pagination (recommended by Crossref) to reliably
iterate through large result sets.

Examples
--------
Export all AACR journal-article DOIs (may take a long time):
  python aacr_journal_dois.py --out aacr_dois.csv

Export DOIs for a specific journal ISSN and date range:
  python aacr_journal_dois.py --issn 0008-5472 --from-pub-date 2026-03-01 --until-pub-date 2025-03-07 --out aacr_doi_test.csv

Set a polite contact email (recommended):
  set CROSSREF_MAILTO=you@company.com
  python aacr_journal_dois.py --out aacr_dois.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import requests


AACR_MEMBER_ID = 1086
WORKS_URL = "https://api.crossref.org/works"
DEFAULT_ROWS = 1000  # Crossref max


@dataclass(frozen=True)
class WorkRow:
    doi: str
    title: str
    journal: str
    issn: str
    published: str


def _best_date_iso(item: dict) -> str:
    """
    Try to derive a best-effort publication date string from Crossref work metadata.
    Returns YYYY-MM-DD / YYYY-MM / YYYY or empty string if unknown.
    """
    for key in ("published-print", "published-online", "issued", "created"):
        parts = ((item.get(key) or {}).get("date-parts") or [])
        if parts and parts[0]:
            ymd = parts[0]
            if len(ymd) == 3:
                return f"{ymd[0]:04d}-{ymd[1]:02d}-{ymd[2]:02d}"
            if len(ymd) == 2:
                return f"{ymd[0]:04d}-{ymd[1]:02d}"
            if len(ymd) == 1:
                return f"{ymd[0]:04d}"
    return ""


def _as_work_row(item: dict) -> WorkRow | None:
    doi = (item.get("DOI") or "").strip()
    if not doi:
        return None

    title = ""
    t = item.get("title")
    if isinstance(t, list) and t:
        title = str(t[0]).strip()
    elif isinstance(t, str):
        title = t.strip()

    journal = ""
    ct = item.get("container-title")
    if isinstance(ct, list) and ct:
        journal = str(ct[0]).strip()
    elif isinstance(ct, str):
        journal = ct.strip()

    issn = ""
    issns = item.get("ISSN")
    if isinstance(issns, list) and issns:
        issn = ";".join([str(x).strip() for x in issns if str(x).strip()])
    elif isinstance(issns, str) and issns.strip():
        issn = issns.strip()

    published = _best_date_iso(item)

    return WorkRow(doi=doi, title=title, journal=journal, issn=issn, published=published)


def iter_aacr_journal_articles(
    *,
    member_id: int = AACR_MEMBER_ID,
    issn: str | None = None,
    from_pub_date: str | None = None,
    until_pub_date: str | None = None,
    query: str | None = None,
    rows: int = DEFAULT_ROWS,
    mailto: str | None = None,
    max_items: int | None = None,
    delay_sec: float = 0.2,
    timeout_sec: float = 60.0,
) -> Iterator[dict]:
    """
    Yield Crossref 'work' items for AACR journal articles.

    Notes:
    - Uses cursor pagination to iterate through large result sets.
    - Crossref asks clients to include a contact email via the `mailto` param.
    - `query` is a general full-text query; use ISSN/date filters for precision.
    """
    if rows < 1 or rows > 1000:
        raise ValueError("rows must be between 1 and 1000")

    filters: list[str] = [f"member:{member_id}", "type:journal-article"]
    if issn:
        filters.append(f"issn:{issn}")
    if from_pub_date:
        filters.append(f"from-pub-date:{from_pub_date}")
    if until_pub_date:
        filters.append(f"until-pub-date:{until_pub_date}")

    params: dict[str, str | int] = {
        "filter": ",".join(filters),
        "rows": rows,
        "cursor": "*",
        "select": "DOI,title,container-title,ISSN,issued,published-print,published-online,created",
    }
    if query:
        params["query"] = query
    if mailto:
        params["mailto"] = mailto

    session = requests.Session()

    yielded = 0
    next_cursor = "*"
    consecutive_empty_pages = 0

    while True:
        params["cursor"] = next_cursor
        for attempt in range(1, 8):
            try:
                resp = session.get(WORKS_URL, params=params, timeout=timeout_sec)
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    sleep_s = float(retry_after) if retry_after and retry_after.isdigit() else min(60.0, 2.0**attempt)
                    time.sleep(sleep_s)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.RequestException:
                if attempt >= 7:
                    raise
                time.sleep(min(30.0, 2.0**attempt))

        msg = (data or {}).get("message") or {}
        items = msg.get("items") or []
        next_cursor = msg.get("next-cursor") or ""

        if not items:
            consecutive_empty_pages += 1
        else:
            consecutive_empty_pages = 0

        for item in items:
            yield item
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return

        # Stop conditions:
        # - no next cursor (rare but possible)
        # - multiple empty pages in a row (defensive)
        if not next_cursor or consecutive_empty_pages >= 3:
            return

        if delay_sec:
            time.sleep(delay_sec)


def export_dois_csv(
    out_path: str | Path,
    *,
    member_id: int = AACR_MEMBER_ID,
    issn: str | None = None,
    from_pub_date: str | None = None,
    until_pub_date: str | None = None,
    query: str | None = None,
    mailto: str | None = None,
    max_items: int | None = None,
) -> int:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["DOI", "published", "journal", "ISSN", "title"],
        )
        w.writeheader()
        for item in iter_aacr_journal_articles(
            member_id=member_id,
            issn=issn,
            from_pub_date=from_pub_date,
            until_pub_date=until_pub_date,
            query=query,
            mailto=mailto,
            max_items=max_items,
        ):
            row = _as_work_row(item)
            if row is None:
                continue
            w.writerow(
                {
                    "DOI": row.doi,
                    "published": row.published,
                    "journal": row.journal,
                    "ISSN": row.issn,
                    "title": row.title,
                }
            )
            n += 1

            if n % 5000 == 0:
                print(f"Wrote {n} rows...", file=sys.stderr)

    return n


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export DOIs for AACR journals using Crossref.")
    p.add_argument("--out", required=True, help="Output CSV path.")
    p.add_argument("--issn", default=None, help="Filter by journal ISSN (print or electronic).")
    p.add_argument("--from-pub-date", default=None, help="Filter from publication date (YYYY-MM-DD).")
    p.add_argument("--until-pub-date", default=None, help="Filter until publication date (YYYY-MM-DD).")
    p.add_argument("--query", default=None, help="Optional full-text query.")
    p.add_argument("--max-items", type=int, default=None, help="Stop after this many works (debug/dev).")
    p.add_argument("--mailto", default=None, help="Contact email for Crossref (or set CROSSREF_MAILTO env var).")
    p.add_argument("--member-id", type=int, default=AACR_MEMBER_ID, help="Crossref member ID (default: 1086 AACR).")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    mailto = args.mailto or os.environ.get("CROSSREF_MAILTO") or None

    n = export_dois_csv(
        args.out,
        member_id=args.member_id,
        issn=args.issn,
        from_pub_date=args.from_pub_date,
        until_pub_date=args.until_pub_date,
        query=args.query,
        mailto=mailto,
        max_items=args.max_items,
    )
    print(f"Done. Wrote {n} DOIs to {args.out}")
    if not mailto:
        print("Tip: set CROSSREF_MAILTO (recommended by Crossref) to identify your requests.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
