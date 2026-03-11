import argparse
import csv
import io
import json
import os
import sys
import tempfile
import time

import requests
from google.cloud import storage

PROJECT_ID = "llm-app-488813"
BATCH_SIZE = 500


def process_batch(doi_batch):
    """
    Process a batch of DOIs using the Semantic Scholar API.
    
    Returns:
        tuple: (jsonl_content: str, failed_dois: list)
    """
    print(f"Processing {len(doi_batch)} DOIs...")
    
    # Use batch API to get details for all DOIs at once
    url = "https://api.semanticscholar.org/graph/v1/paper/batch"
    
    try:
        response = requests.post(
            url,
            params={"fields": "title,abstract,url,publicationDate,publicationTypes,journal"},
            json={"ids": doi_batch},
            timeout=30
        )
        response.raise_for_status()
    except Exception as e:
        print(f"Error calling Semantic Scholar API: {e}")
        return "", doi_batch
    
    data = response.json()
    
    # Convert the list of dicts to JSON Lines string
    jsonl_content = ""
    failed_dois = []
    
    # Process each paper in the response (same order as doi_batch)
    for i, paper in enumerate(data):
        doi = doi_batch[i]
        if paper is None:
            # Paper not found
            failed_dois.append(doi)
            jsonl_content += json.dumps({'doi': doi, 'error': 'Paper not found'}) + "\n"
            continue
        
        # Extract required fields
        paper_data = {
            'doi': doi,
            'url': paper.get('url'),
            'title': paper.get('title'),
            'abstract': paper.get('abstract'),
            'publicationDate': paper.get('publicationDate'),
            'publicationTypes': paper.get('publicationTypes'),
            'journal': paper.get('journal')
        }
        jsonl_content += json.dumps(paper_data) + "\n"
    
    return jsonl_content, failed_dois


def save_to_gcs(content, blob_name):
    """Save content to Google Cloud Storage."""
    try:
        client = storage.Client()
        bucket = client.bucket("aacr-abstracts-data-lake")
        blob = bucket.blob(blob_name)
        blob.upload_from_string(content, content_type='application/jsonl')
        print(f"Saved to gs://aacr-abstracts-data-lake/{blob_name}")
        return True
    except Exception as e:
        print(f"Error saving to GCS: {e}")
        return False


def save_failed_dois_to_gcs(failed_dois, blob_name):
    """Save failed DOIs to GCS for retry."""
    if not failed_dois:
        return True
    
    content = json.dumps(failed_dois)
    return save_to_gcs(content, blob_name)


def load_dois_from_csv(gcs_path):
    """Load DOIs from CSV file on Google Cloud Storage."""
    dois = []
    
    try:
        # Parse GCS path: gs://bucket-name/path/to/file.csv
        if not gcs_path.startswith('gs://'):
            raise ValueError("GCS path must start with 'gs://'")
        
        path_parts = gcs_path[5:].split('/', 1)  # Remove 'gs://' and split bucket from path
        if len(path_parts) != 2:
            raise ValueError("Invalid GCS path format")
        
        bucket_name, blob_name = path_parts
        
        # Download file from GCS
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        # Download as string
        csv_content = blob.download_as_text(encoding='utf-8')
        
        # Parse CSV from string
        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            # Assuming the CSV has a 'doi' column (adjust if needed)
            doi = row.get('doi') or row.get('DOI')
            if doi:
                dois.append(doi)
                
    except Exception as e:
        print(f"Error loading CSV from GCS: {e}")
        return dois
    
def load_dois_from_json(gcs_path):
    """Load DOIs from JSON file on Google Cloud Storage."""
    dois = []
    
    try:
        # Parse GCS path: gs://bucket-name/path/to/file.json
        if not gcs_path.startswith('gs://'):
            raise ValueError("GCS path must start with 'gs://'")
        
        path_parts = gcs_path[5:].split('/', 1)  # Remove 'gs://' and split bucket from path
        if len(path_parts) != 2:
            raise ValueError("Invalid GCS path format")
        
        bucket_name, blob_name = path_parts
        
        # Download file from GCS
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        # Download as string and parse JSON
        json_content = blob.download_as_text(encoding='utf-8')
        dois = json.loads(json_content)
        
    except Exception as e:
        print(f"Error loading JSON from GCS: {e}")
        return dois
    
    print(f"Loaded {len(dois)} DOIs from {gcs_path}")
    return dois


def main():
    parser = argparse.ArgumentParser(
        description='Process DOIs from CSV file and save paper details to GCS.'
    )
    parser.add_argument(
        '--csv-file',
        type=str,
        default=None,
        help='GCS path to CSV file containing DOIs. Default is gs://aacr-abstracts-data-lake/combined_aacr_results.csv'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=BATCH_SIZE,
        help=f'Number of DOIs to process in each batch. Default is {BATCH_SIZE}.'
    )
    parser.add_argument(
        '--failed-dois-json',
        type=str,
        default=None,
        help='Optional GCS path to JSON file containing failed DOIs to retry. If provided, loads DOIs from this JSON instead of CSV.'
    )
    args = parser.parse_args()
    print(sys.argv)
    
    # Load DOIs from CSV or JSON
    if args.failed_dois_json:
        print("Loading DOIs from failed DOIs JSON file...")
        dois = load_dois_from_json(args.failed_dois_json)
    else:
        print("Loading DOIs from CSV file...")
        dois = load_dois_from_csv(args.csv_file)
    if not dois:
        print("No DOIs to process.")
        return
    
    # Process in batches
    total_batches = (len(dois) + args.batch_size - 1) // args.batch_size
    all_failed_dois = []
    
    # We'll accumulate JSONL for up to save_frequency batches before saving
    temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.jsonl')
    batches_since_save = 0
    save_freq = args.save_frequency

    def flush_temp_file(batch_num, doi_batch):
        nonlocal temp_file
        temp_file.flush()
        temp_file.seek(0)
        blob_name = f"aacr_publication/paper_details_batches_{int(time.time())}_{batch_num}.jsonl"
        success = save_to_gcs(temp_file.read(), blob_name)
        temp_file.close()
        os.unlink(temp_file.name)
        temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.jsonl')
        if not success:
            # if upload failed, mark current batch DOIs as failed
            all_failed_dois.extend(doi_batch)
        return success

    for batch_num in range(total_batches):
        start_idx = batch_num * args.batch_size
        end_idx = min(start_idx + args.batch_size, len(dois))
        doi_batch = dois[start_idx:end_idx]

        print(f"\nProcessing batch {batch_num + 1}/{total_batches} ({len(doi_batch)} DOIs)...")

        # Process the batch
        jsonl_content, failed_dois = process_batch(doi_batch)

        # Accumulate results
        if jsonl_content:
            temp_file.write(jsonl_content)
            batches_since_save += 1
        else:
            # if the call returned no content, consider entire batch failed
            all_failed_dois.extend(doi_batch)

        # Track failed DOIs
        all_failed_dois.extend(failed_dois)

        # Flush to GCS every save_freq batches (or at end)
        if batches_since_save >= save_freq or batch_num == total_batches - 1:
            if os.path.getsize(temp_file.name) > 0:
                flush_temp_file(batch_num, doi_batch)
                batches_since_save = 0

        # Add small delay between requests to avoid rate limiting
        if batch_num < total_batches - 1:
            time.sleep(1)
    
    # Save any failed DOIs to GCS
    if all_failed_dois:
        print(f"\n{len(all_failed_dois)} DOIs failed. Saving failed DOI list to GCS...")
        save_failed_dois_to_gcs(all_failed_dois, f"failed_dois_{int(time.time())}.json")
    
    print("\nProcessing complete!")


if __name__ == "__main__":
    main()
