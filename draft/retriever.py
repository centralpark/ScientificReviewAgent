from google.cloud import discoveryengine_v1 as discoveryengine
import os

PROJECT_ID = os.environ.get("PROJECT_ID", "llm-app-488813")
LOCATION = "global"
DATA_STORE_ID = os.environ.get("DATA_STORE_ID", "aacr-abstracts_1773385412104")

def retrieve_aacr_abstracts(search_query: str, top_k: int = 10) -> list:
    """Queries Vertex AI Search and returns structured research chunks."""

    client = discoveryengine.SearchServiceClient()
    serving_config = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/engines/{DATA_STORE_ID}/servingConfigs/default_config"

    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=search_query,
        page_size=top_k,
        content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
            # Enable Snippets to get the exact matching sentences
            snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                return_snippet=True
            ),
            # Extract the actual structured data we mapped earlier
            extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                max_extractive_answer_count=1
            )
        )
    )

    response = client.search(request)

    retrieved_docs =[]
    for result in response.results:
        # Parse the custom JSON structure returned by the API
        doc_dict = type(result.document).to_dict(result.document)
        struct_data = doc_dict.get("struct_data", {})

        retrieved_docs.append({
            "doi": struct_data.get("doi", "Unknown DOI"),
            "title": struct_data.get("title", "Untitled"),
            "abstract": struct_data.get("abstract", "")
        })

    return retrieved_docs


