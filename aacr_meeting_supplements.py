"""
Query Crossref API for all AACR journal publications flagged as meeting supplements.

Meeting supplements are identified by the issue field containing "Supplement"
(e.g. "19_Supplement", "11_Supplement") in AACR journal articles.
"""

import requests
import time
from pathlib import Path

# AACR Crossref member ID (American Association for Cancer Research)
AACR_MEMBER_ID = 1086
BASE_URL = "https://api.crossref.org"
ROWS_PER_PAGE = 1000  # API max is 1000
DELAY_SEC = 1.0       # polite delay between requests


def is_meeting_supplement(item: dict) -> bool:
    """Return True if the work is a journal meeting supplement (issue contains 'Supplement')."""
    issue = (
        item.get("issue")
        or (item.get("journal-issue") or {}).get("issue")
        or ""
    )
    return "supplement" in str(issue).lower()


def fetch_aacr_meeting_supplements(
    *,
    member_id: int = AACR_MEMBER_ID,
    out_path: str | Path | None = None,
    max_works: int | None = None,
) -> list[dict]:
    """
    Query Crossref for all AACR journal-articles and return those that are meeting supplements.

    Optionally save results to a JSON file and/or limit total works scanned.
    """
    url = f"{BASE_URL}/members/{member_id}/works"
    params = {
        "filter": "type:journal-article",
        "rows": ROWS_PER_PAGE,
        "offset": 0,
    }
    all_supplements = []
    total_scanned = 0

    while True:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {})
        items = msg.get("items", [])
        total = msg.get("total-results", 0)

        for item in items:
            total_scanned += 1
            if is_meeting_supplement(item):
                all_supplements.append(item)
            if max_works is not None and total_scanned >= max_works:
                break

        if max_works is not None and total_scanned >= max_works:
            break
        if not items or params["offset"] + len(items) >= total:
            break

        params["offset"] += len(items)
        time.sleep(DELAY_SEC)

    if out_path is not None:
        import json
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(all_supplements, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(all_supplements)} meeting supplements to {path}")

    return all_supplements


def main():
    import json
    print("Querying Crossref for AACR meeting supplements (journal-articles with issue containing 'Supplement')...")
    supplements = fetch_aacr_meeting_supplements(
        out_path=Path(__file__).parent / "aacr_meeting_supplements.json",
    )
    print(f"Found {len(supplements)} meeting supplement publications.")
    if supplements:
        print("\nFirst 3 DOIs:")
        for item in supplements[:3]:
            print(f"  {item.get('DOI')} - {item.get('container-title', [''])[0]} {item.get('volume', '')}({item.get('issue', '')})")
    return supplements


if __name__ == "__main__":
    main()
