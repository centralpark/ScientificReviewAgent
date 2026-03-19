"""
Wraps a flat JSON/JSONL file from GCS into the Vertex AI Search document envelope format.

Each input record becomes:
    {
        "id": "<sanitized DOI>",
        "structData": { <all original fields> }
    }

ID sanitization: Vertex AI only allows letters, numbers, hyphens, and underscores.
All other characters (e.g. "/" and ".") are replaced with "_".

Usage:
    INPUT_GCS_PATH=gs://my-bucket/path/to/input.json \
    OUTPUT_GCS_PATH=gs://my-bucket/path/to/output.jsonl \
    python wrap_to_vertex_jsonl.py
"""

import json
import os
import re
import sys

from google.cloud import storage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_gcs_path(gcs_path: str) -> tuple[str, str]:
    """Return (bucket_name, blob_name) from a gs:// URI."""
    if not gcs_path.startswith("gs://"):
        raise ValueError(f"GCS path must start with 'gs://': {gcs_path}")
    parts = gcs_path[5:].split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise ValueError(f"Invalid GCS path (must include bucket and object): {gcs_path}")
    return parts[0], parts[1]


def sanitize_id(doi: str) -> str:
    """Replace characters not allowed by Vertex AI with underscores."""
    return re.sub(r"[^A-Za-z0-9\-_]", "_", doi)


def normalize_date(value: str) -> str:
    """
    Normalize a publication date string to YYYY-MM-DD for Vertex AI ingestion.
      - YYYY-MM-DD → returned as-is
      - YYYY-MM    → YYYY-MM-01
      - YYYY       → YYYY-01-01
      - anything else (empty, null, unrecognized) → 1970-01-01
    """
    if not value or not isinstance(value, str):
        return "1970-01-01"
    v = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v
    if re.fullmatch(r"\d{4}-\d{2}", v):
        return f"{v}-01"
    if re.fullmatch(r"\d{4}", v):
        return f"{v}-01-01"
    return "1970-01-01"


def load_records_from_gcs(gcs_path: str) -> list[dict]:
    """
    Download a file from GCS and parse it as either:
      - JSONL  (one JSON object per line), or
      - a JSON array / single JSON object.
    Returns a flat list of dicts.
    """
    bucket_name, blob_name = parse_gcs_path(gcs_path)

    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    text = blob.download_as_text(encoding="utf-8")

    records = []

    # Try JSONL first (each non-empty line is a JSON object)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    try:
        for line in lines:
            records.append(json.loads(line))
        print(f"Parsed {len(records)} records as JSONL from {gcs_path}")
        return records
    except json.JSONDecodeError:
        pass  # fall through to full-document JSON parse

    # Fall back to parsing as a single JSON document
    data = json.loads(text)
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = [data]
    else:
        raise ValueError("Input JSON must be an array of objects or a single object.")

    print(f"Parsed {len(records)} records as JSON from {gcs_path}")
    return records


def wrap_record(record: dict) -> dict:
    """Wrap a flat record into the Vertex AI Search document envelope."""
    doi = record.get("DOI") or record.get("doi", "")
    if not doi:
        raise ValueError(f"Record is missing a DOI field: {record}")

    if "publicationDate" in record:
        record = {**record, "publicationDate": normalize_date(record["publicationDate"])}

    return {
        "id": sanitize_id(doi),
        "structData": record,
    }


def upload_jsonl_to_gcs(records: list[dict], gcs_path: str) -> None:
    """Serialize records as JSONL and upload to GCS."""
    bucket_name, blob_name = parse_gcs_path(gcs_path)

    content = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"

    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_string(content, content_type="application/jsonl")
    print(f"Uploaded {len(records)} records to gs://{bucket_name}/{blob_name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    input_path = os.environ.get("INPUT_GCS_PATH", "").strip()
    output_path = os.environ.get("OUTPUT_GCS_PATH", "").strip()

    if not input_path:
        print("ERROR: INPUT_GCS_PATH environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    if not output_path:
        print("ERROR: OUTPUT_GCS_PATH environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")

    records = load_records_from_gcs(input_path)
    if not records:
        print("No records found in input. Exiting.")
        sys.exit(0)

    wrapped = []
    errors = 0
    for i, record in enumerate(records):
        try:
            wrapped.append(wrap_record(record))
        except ValueError as exc:
            print(f"  [WARNING] Skipping record {i}: {exc}")
            errors += 1

    print(f"Wrapped {len(wrapped)} records ({errors} skipped).")
    upload_jsonl_to_gcs(wrapped, output_path)
    print("Done.")


if __name__ == "__main__":
    main()
