import pandas as pd
from google.cloud import storage
from io import StringIO

def read_all_csvs(bucket_name):
    # Initialize the Storage Client
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    # List all blobs in the bucket
    blobs = list(bucket.list_blobs())
    
    # Filter blobs that match the pattern "aacr_results_{year}.csv"
    # Assuming year is 4 digits
    matching_blobs = [
        blob for blob in blobs
        if blob.name.startswith('aacr_results_') and blob.name.endswith('.csv')
    ]
    
    all_dfs = []
    total_files = 0
    
    for blob in matching_blobs:
        print(f"Reading {blob.name}...")
        content = blob.download_as_text()
        df = pd.read_csv(StringIO(content))
        all_dfs.append(df)
        total_files += 1
        print(f"  - Shape: {df.shape}")
    
    if all_dfs:
        # Combine all DataFrames
        combined_df = pd.concat(all_dfs, ignore_index=True)
        combined_df = combined_df['DOI'].dropna().to_frame()  # Keep only the DOI column and drop rows with NaN DOIs
        print(f"\nTotal files read: {total_files}")
        print(f"Combined DataFrame shape: {combined_df.shape}")
        
        # Optionally, save the combined CSV to GCS
        combined_blob = bucket.blob("combined_aacr_results.csv")
        combined_csv_content = combined_df.to_csv(index=False)
        combined_blob.upload_from_string(combined_csv_content, content_type='text/csv')
        print("Combined CSV uploaded to GCS as 'combined_aacr_results.csv'")
        
        return combined_df
    else:
        print("No matching CSV files found.")
        return None

if __name__ == "__main__":
    read_all_csvs("aacr-abstracts-data-lake")