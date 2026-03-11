import pandas as pd
from google.cloud import pubsub_v1, storage
import os
import json
from io import StringIO

# Configuration
PROJECT_ID = "llm-app-488813"
TOPIC_ID = "topic_doi"

def publish_doi_to_pubsub(csv_file, bucket_name):
    # 1. Initialize the Publisher Client
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

    # 2. Read CSV from Google Cloud Storage
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(csv_file)
    content = blob.download_as_text()
    df = pd.read_csv(StringIO(content))
    
    # Ensure your CSV has a column named 'DOI' (case-sensitive)
    dois = df['DOI'].dropna().tolist()
    
    print(f"Starting to publish {len(dois)} DOIs to {topic_path} in messages of 500 DOIs each...")

    # 3. Publish DOIs in batches of 500 as single messages
    chunk_size = 500
    for i in range(0, len(dois), chunk_size):
    # for i in range(1):  # For testing, only publish the first chunk
        chunk = dois[i:i + chunk_size]
        print(f"Publishing message {i // chunk_size + 1} with {len(chunk)} DOIs...")
        
        # Serialize the chunk as JSON
        data = json.dumps(chunk).encode("utf-8")
        
        # Publish the entire chunk as a single message
        future = publisher.publish(topic_path, data)
        
        print(future.result())

    
    print("Done! All messages published to the queue.")
    
    
def main():
    years = [str(i) for i in range(2004, 2027)]
    task_index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", 0))

    if task_index < len(years):
        target_year = years[task_index]
        print(f"Task {task_index} is processing year {target_year}")
        csv_file = f"aacr_results_{target_year}.csv"
        bucket_name = "aacr-abstracts-data-lake"
        publish_doi_to_pubsub(csv_file, bucket_name)


if __name__ == "__main__":
    raise SystemExit(main())