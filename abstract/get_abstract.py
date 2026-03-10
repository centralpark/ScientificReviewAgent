import argparse
import json
import time
from concurrent.futures import TimeoutError

import requests
from google.cloud import pubsub_v1, storage

PROJECT_ID = "llm-app-488813"
SUBSCRIPTION_ID = "sub_abstract"

# Global variables for accumulating JSONL content
message_count = 0
accumulated_jsonl = ""

def process_msg(msg):
    print(f"Processing {len(msg)} DOIs...")
    
    # Use batch API to get details for all DOIs at once
    url = "https://api.semanticscholar.org/graph/v1/paper/batch"
    
    response = requests.post(
        url,
        params={"fields": "title,abstract,url,publicationDate,publicationTypes,journal"},
        json={"ids": [doi for doi in msg]},
        timeout=30
    )
    response.raise_for_status()
    
    data = response.json()
    
    # Convert the list of dicts to JSON Lines string
    jsonl_content = ""
    
    # Process each paper in the response (same order as msg)
    for i, paper in enumerate(data):
        doi = msg[i]
        if paper is None:
            # Paper not found
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
    
    return jsonl_content



def save_accumulated_to_gcs():
    global accumulated_jsonl, message_count
    if not accumulated_jsonl:
        return
    
    # Save results to GCS as JSONL
    client = storage.Client()
    bucket = client.bucket("aacr-abstracts-data-lake")
    blob_name = f"aacr_publication/paper_details_batch_{int(time.time())}.jsonl"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(accumulated_jsonl, content_type='application/jsonl')
    
    print(f"Saved {message_count} messages ({len(accumulated_jsonl.splitlines())} records) to gs://aacr-abstracts-data-lake/{blob_name}")
    
    # Reset
    accumulated_jsonl = ""
    message_count = 0



def callback(message):
    global message_count, accumulated_jsonl
    try:
        # Decode the message data as JSON (list of DOIs)
        doi_list = json.loads(message.data.decode("utf-8"))
        jsonl_content = process_msg(doi_list)
        accumulated_jsonl += jsonl_content
        message_count += 1
        
        # Save every batch_size messages
        if message_count >= batch_size:
            save_accumulated_to_gcs()
        
        message.ack()  # Tell Pub/Sub: "I did it! Delete this message from the queue."
    except Exception as e:
        print(f"Error processing message: {e}")
        message.nack()  # Tell Pub/Sub: "I failed! Put it back in the queue."



def main():
    parser = argparse.ArgumentParser(
        description=('Process DOI messages from Pub/Sub and save '
                     'paper details to GCS.')
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=200,
        help=('Number of messages to accumulate before saving to GCS. '
              'Default is 200.')
    )
    args = parser.parse_args()
    
    global batch_size
    batch_size = args.batch_size
    
    print(f"Batch size: {batch_size}")
    # Boilerplate to keep the worker running
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

    streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
    print(f"Listening for messages on {subscription_path}...")

    try:
        streaming_pull_future.result(timeout=60.0)
    except TimeoutError:
        save_accumulated_to_gcs()
        streaming_pull_future.cancel()

if __name__ == "__main__":
    main()