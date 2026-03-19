"""
Scan AACR Crossref-export JSONL files (from `aacr_journal_dois.py`) stored on
Google Cloud Storage, fill in missing abstracts via the Semantic Scholar batch
API (same approach as `process_aacr_dois.py`), and write a single merged JSONL
back to GCS.

Behavior
--------
- Lists all blobs in `--gcs-bucket` whose names match `--input-pattern` (fnmatch-style glob, e.g. aacr_results_*.jsonl)
- Streams each blob line by line:
  - Records with a non-empty `abstract` are written to a local temp file as-is
  - Records with an empty `abstract` are buffered; once 500 accumulate they are
    enriched in a single Semantic Scholar batch call and then written to the temp file
- Uploads the temp file to `gs://<gcs-bucket>/<out-blob>` and deletes it
- Writes any failed DOIs (not found / API error) to `gs://<gcs-bucket>/<failed-dois-blob>`
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import tempfile
import time
from typing import Any, Dict, List, Tuple

import requests

from google.cloud import storage  # type: ignore


BUCKET_NAME = "aacr-abstracts-data-lake"
DEFAULT_BATCH_SIZE = 500
DEFAULT_FIELDS = "title,abstract"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"


def _is_empty_abstract(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        value = str(value)
    return value.strip() == ""


def _process_batch(
    dois: List[str],
    *,
    fields: str = DEFAULT_FIELDS,
    timeout_sec: float = 30.0,
) -> Tuple[List[dict | None], List[str]]:
    """
    Call Semantic Scholar batch endpoint.

    Returns:
        (papers, failed_dois)
        papers is aligned with `dois`; each entry is a dict or None.
        failed_dois are DOIs whose lookup definitively failed.
    """
    if not dois:
        return [], []

    response = None
    for attempt in range(1, 6):
        try:
            response = requests.post(
                S2_BATCH_URL,
                params={"fields": fields},
                json={"ids": dois},
                timeout=timeout_sec,
            )
            if response.status_code == 429:
                time.sleep(min(60.0, 2.0**attempt))
                continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise ValueError("Unexpected Semantic Scholar response shape (expected list)")
            return data, []
        except Exception:
            if attempt >= 5:
                break
            time.sleep(min(30.0, 2.0**attempt))

    if response is not None and response.status_code == 400 and "No valid paper ids" in (response.text or ""):
        return [], []
    return [None] * len(dois), list(dois)


def _list_input_blobs(client: storage.Client, bucket_name: str, pattern: str) -> List[storage.Blob]:
    """List blobs in `bucket_name` whose names match the fnmatch-style `pattern` (e.g. 'aacr_results_*.jsonl')."""
    bucket = client.bucket(bucket_name)
    # Use the portion before the first wildcard as a server-side prefix to reduce listed results
    prefix = pattern.split("*")[0].split("?")[0].split("[")[0]
    blobs = [b for b in client.list_blobs(bucket, prefix=prefix or None) if fnmatch.fnmatch(b.name, pattern)]
    return sorted(blobs, key=lambda b: b.name)


def _upload_file_to_gcs(client: storage.Client, bucket_name: str, blob_name: str, local_path: str, content_type: str) -> None:
    """Upload a local file to GCS without reading it into memory."""
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path, content_type=content_type)
    print(f"Uploaded to gs://{bucket_name}/{blob_name}")


def _upload_string_to_gcs(client: storage.Client, bucket_name: str, blob_name: str, content: str, content_type: str) -> None:
    """Upload a small in-memory string to GCS."""
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(content, content_type=content_type)
    print(f"Uploaded to gs://{bucket_name}/{blob_name}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fill missing abstracts in AACR Crossref JSONL exports on GCS via Semantic Scholar."
    )
    parser.add_argument(
        "--gcs-bucket",
        type=str,
        default=BUCKET_NAME,
        help=f"GCS bucket containing input files and where outputs will be written. Default: {BUCKET_NAME}",
    )
    parser.add_argument(
        "--input-pattern",
        type=str,
        default="aacr_results_*.jsonl",
        help="fnmatch-style pattern to match input JSONL blob names in the bucket. Default: aacr_results_*.jsonl",
    )
    parser.add_argument(
        "--out-blob",
        type=str,
        default="aacr_final_results.jsonl",
        help="Blob name for the merged output JSONL. Default: aacr_final_results.jsonl",
    )
    parser.add_argument(
        "--failed-dois-blob",
        type=str,
        default="failed_missing_abstract_dois.json",
        help="Blob name for the failed DOI list JSON. Default: failed_missing_abstract_dois.json",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Records with missing abstract to enrich per batch. Default: {DEFAULT_BATCH_SIZE}",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=1.0,
        help="Delay in seconds between Semantic Scholar batch requests. Default: 1.0",
    )
    args = parser.parse_args()

    client = storage.Client()

    input_blobs = _list_input_blobs(client, args.gcs_bucket, args.input_pattern)
    if not input_blobs:
        raise SystemExit(f"No blobs found in gs://{args.gcs_bucket} matching pattern '{args.input_pattern}'")

    print(f"Found {len(input_blobs)} input blob(s):")
    for b in input_blobs:
        print(f"  gs://{args.gcs_bucket}/{b.name}")

    seen_dois: set[str] = set()
    pending_records: List[Dict[str, Any]] = []
    pending_dois: List[str] = []
    failed_dois: List[str] = []

    total_read = 0
    total_missing = 0

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".jsonl")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as out_f:

            def flush_pending() -> None:
                nonlocal pending_records, pending_dois, failed_dois
                if not pending_records:
                    return

                print(f"  Enriching batch of {len(pending_records)} DOIs via Semantic Scholar...")
                papers, batch_failed = _process_batch(pending_dois)
                failed_dois.extend(batch_failed)

                batch_failed_set = set(batch_failed)
                for rec, doi, paper in zip(pending_records, pending_dois, papers):
                    if paper is None:
                        if doi not in batch_failed_set:
                            failed_dois.append(doi)
                    else:
                        abstract = paper.get("abstract") if isinstance(paper, dict) else None
                        if not _is_empty_abstract(abstract):
                            rec["abstract"] = abstract
                        # else: Semantic Scholar also has no abstract; keep record as-is
                    out_f.write(json.dumps(rec, ensure_ascii=False))
                    out_f.write("\n")

                pending_records.clear()
                pending_dois.clear()

            for blob in input_blobs:
                gcs_path = f"gs://{args.gcs_bucket}/{blob.name}"
                print(f"Reading {gcs_path} ...")
                text = blob.download_as_text(encoding="utf-8")

                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    total_read += 1
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(rec, dict):
                        continue

                    doi = (rec.get("DOI") or rec.get("doi") or "").strip()
                    if not doi or doi in seen_dois:
                        continue
                    seen_dois.add(doi)

                    if not _is_empty_abstract(rec.get("abstract")):
                        out_f.write(json.dumps(rec, ensure_ascii=False))
                        out_f.write("\n")
                        continue

                    total_missing += 1
                    pending_records.append(rec)
                    pending_dois.append(doi)

                    if len(pending_records) >= args.batch_size:
                        flush_pending()
                        if args.sleep_sec:
                            time.sleep(args.sleep_sec)

            flush_pending()
        # out_f is closed here; tmp_path is ready for upload

        # Deduplicate failed DOIs while preserving order
        seen_failed: set[str] = set()
        failed_unique: List[str] = []
        for d in failed_dois:
            if d and d not in seen_failed:
                seen_failed.add(d)
                failed_unique.append(d)

        print(f"\nSummary:")
        print(f"  Input blobs:                   {len(input_blobs)}")
        print(f"  Records read:                  {total_read}")
        print(f"  Unique DOIs:                   {len(seen_dois)}")
        print(f"  Missing abstract (enriched):   {total_missing}")
        print(f"  Failed DOIs:                   {len(failed_unique)}")

        _upload_file_to_gcs(client, args.gcs_bucket, args.out_blob, tmp_path, "application/jsonl")
        _upload_string_to_gcs(
            client,
            args.gcs_bucket,
            args.failed_dois_blob,
            json.dumps(failed_unique, ensure_ascii=False, indent=2),
            "application/json",
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
