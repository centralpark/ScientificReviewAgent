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

import json
import os
import sys
import time
from typing import Iterator
from google.cloud import storage

import requests


AACR_MEMBER_ID = 1086
WORKS_URL = "https://api.crossref.org/members/1086/works"
DEFAULT_ROWS = 100


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

def _published_date_iso(item: dict) -> str:
    """
    Construct publicationDate from Crossref `published.date-parts`.
    Returns YYYY-MM-DD / YYYY-MM / YYYY or empty string if unknown.
    """
    parts = ((item.get("published") or {}).get("date-parts") or [])
    if not parts or not parts[0]:
        return ""
    ymd = parts[0]
    if len(ymd) == 3:
        return f"{ymd[0]:04d}-{ymd[1]:02d}-{ymd[2]:02d}"
    if len(ymd) == 2:
        return f"{ymd[0]:04d}-{ymd[1]:02d}"
    if len(ymd) == 1:
        return f"{ymd[0]:04d}"
    return ""


def iter_aacr_journal_articles(
    *,
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

    # Crossref Filters:
    filters: list[str] = []
    if issn:
        filters.append(f"issn:{issn}")
    if from_pub_date:
        filters.append(f"from-pub-date:{from_pub_date}")
    if until_pub_date:
        filters.append(f"until-pub-date:{until_pub_date}")

    params: dict[str, str | int] = {
        "filter": ",".join(filters),
        "cursor": "*",
        "rows": rows,
    }
    params["select"] = "DOI,title,type,abstract,URL,published,container-title,issue,page"
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


def main() -> int:
    years = [str(i) for i in range(2004, 2027)]
    task_index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", 0))
    # years = ['2004']
    # task_index = 0

    if task_index < len(years):
        target_year = years[task_index]
        print(f"Task {task_index} is processing year {target_year}")
        from_pub_date = f"{target_year}-01-01"
        until_pub_date = f"{target_year}-12-31"
    
    mailto = "siheng.he@rinuagene.com"
    max_items = None
    
    local_path = f"aacr_results_{target_year}.jsonl"
    
    count = 0
    with open(local_path, "w", encoding="utf-8") as f:
        for item in iter_aacr_journal_articles(
            from_pub_date=from_pub_date,
            until_pub_date=until_pub_date,
            mailto=mailto,
            max_items=max_items,
        ):
            article_type = item.get("type") or ""
            if article_type not in ["journal-article", "proceedings-article"]:
                continue

            record = {
                "DOI": item.get("DOI") or "",
                "title": (item.get("title") or [""])[0] if isinstance(item.get("title"), list) else (item.get("title") or ""),
                "type": article_type,
                "abstract": item.get("abstract") or "",
                "URL": item.get("URL") or "",
                "publicationDate": _published_date_iso(item),
                "container-title": (item.get("container-title") or [""])[0]
                if isinstance(item.get("container-title"), list)
                else (item.get("container-title") or ""),
                "issue": item.get("issue") or "", # journal-issue is not available
                "page": item.get("page") or "",
            }

            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")

            count += 1
            if count % 1000 == 0:
                print(f"{count} items written so far...")
        
    print(f"Total items written: {count}")

    # Upload to Google Cloud Storage so it persists!
    client = storage.Client()
    bucket = client.bucket("aacr-abstracts-data-lake")
    blob = bucket.blob(f"aacr_results_{target_year}.jsonl")
    
    blob.upload_from_filename(local_path)
    print("Upload complete! Job finished.")
    
    if not mailto:
        print("Tip: set CROSSREF_MAILTO (recommended by Crossref) to identify your requests.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
