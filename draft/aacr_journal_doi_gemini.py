import requests
import time
import json

def fetch_aacr_publications(start_date, end_date):
    """
    Fetches publications from the Crossref API for AACR within a date range.
    """
    
    # member:1086 = American Association for Cancer Research (AACR)
    base_url = "https://api.crossref.org/members/1086/works"
    
    # ⚠️ IMPORTANT: Replace with your actual email to use the fast "Polite Pool"
    email = "siheng.he@rinuagene.com" 
    
    # Crossref Filters:
    # type:journal-article = Filters out book chapters or errata (optional but recommended)
    # Change "from-pub-date" to "from-deposit-date"
    filters = f"from-deposit-date:{start_date},until-deposit-date:{end_date}"
    
    # Initialize the cursor to the asterisk wildcard (meaning "start at page 1")
    cursor = "*"
    all_publications =[]
    
    print(f"Starting extraction for AACR publications between {start_date} and {end_date}...\n")
    
    while cursor:
        params = {
            "filter": filters,
            "rows": 100,      # Max items returned per request
            "cursor": cursor, # Token for the next page
            "mailto": email   # Polite pool routing
        }
        
        try:
            response = requests.get(base_url, params=params, timeout=10)
            response.raise_for_status() # Raise an exception for HTTP errors (404, 500, etc.)
        except requests.exceptions.RequestException as e:
            print(f"API Request failed: {e}")
            break
            
        data = response.json()
        
        # Extract the items array
        items = data.get("message", {}).get("items",[])
        
        if not items:
            print("No more items found. Pagination complete.")
            break
            
        all_publications.extend(items)
        print(f"Fetched {len(items)} items... (Total so far: {len(all_publications)})")
        
        # Get the cursor string for the *next* page
        next_cursor = data.get("message", {}).get("next-cursor")
        
        # If the cursor hasn't changed or is empty, we've reached the end
        if next_cursor == cursor or not next_cursor:
            break
            
        cursor = next_cursor
        
        # Be a good internet citizen - slight delay to avoid hammering the API
        time.sleep(0.5)
        
    return all_publications

if __name__ == "__main__":
    # Check from Jan 1st to today
    START_DATE = "2026-01-01"
    END_DATE = "2026-03-09"
    
    # Execute the extraction
    publications = fetch_aacr_publications(START_DATE, END_DATE)
    
    print(f"\n✅ Total AACR publications found in March 2026: {len(publications)}\n")
    
    # Print the metadata for the first 5 abstracts as a preview
    for i, pub in enumerate(publications[:5], 1):
        # Crossref returns titles and authors as arrays
        title = pub.get("title", ["No Title Available"])[0]
        doi = pub.get("DOI", "No DOI")
        url = pub.get("URL", "No URL")
        
        # Gracefully handle authors (sometimes abstracts don't list them properly)
        authors = pub.get("author",[])
        author_names = ", ".join([f"{a.get('given', '')} {a.get('family', '')}".strip() for a in authors[:3]])
        if len(authors) > 3:
            author_names += " et al."
            
        print(f"{i}. {title}")
        print(f"   Authors: {author_names or 'N/A'}")
        print(f"   DOI: {doi}")
        print(f"   Link: {url}\n")
        
    # Optional: Save the raw dataset locally to check the JSON structure
    with open("aacr_feb_2026_raw.json", "w", encoding="utf-8") as f:
        json.dump(publications, f, indent=4)
        print("Raw data saved to 'aacr_feb_2026_raw.json'")