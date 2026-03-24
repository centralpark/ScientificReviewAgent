import datetime as _dt
import os
import re
from typing import List, Optional

import requests
from dotenv import load_dotenv
from google.cloud import discoveryengine_v1 as discoveryengine
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool
from pydantic import BaseModel, Field

load_dotenv(override=False)

PROJECT_ID = os.environ.get("PROJECT_ID")
LOCATION = "global"
DATA_STORE_ID = os.environ.get("DATA_STORE_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")


def _require_runtime_config() -> None:
    missing = []
    if not PROJECT_ID:
        missing.append("PROJECT_ID")
    if not DATA_STORE_ID:
        missing.append("DATA_STORE_ID")
    if not GOOGLE_API_KEY:
        missing.append("GOOGLE_API_KEY")
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Set them before starting the app."
        )


def _strip_jats(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _years_ago_iso(
    years: int, months: int = 0, days: int = 0, today: Optional[_dt.date] = None
) -> str:
    """Return YYYY-MM-DD for (today - years), preserving month/day when possible."""
    if today is None:
        today = _dt.date.today()
    try:
        cutoff = _dt.date(today.year - years, today.month, today.day)
    except ValueError:
        # Handles Feb 29 -> Feb 28 in non-leap years, etc.
        cutoff = _dt.date(today.year - years, today.month, 28)
    return cutoff.isoformat()


@tool("compute_date")
def compute_date(years: int, months: int = 0, days: int = 0) -> str:
    """Compute the date (YYYY-MM-DD) that is `years` years, `months` months, and `days` days before today.

    Args:
        years: Number of years to subtract from today's date
        months: Optional, number of months to subtract from today's date
        days: Optional, number of days to subtract from today's date
    """
    return _years_ago_iso(years, months, days)


@tool("tavily_web_search")
def tavily_web_search(query: str, max_results: int = 10) -> str:
    """Search the live web using Tavily for up-to-date information, scientific news, and general facts.

    Args:
        query: The search query
        max_results: The maximum number of results to return
    """
    api_key = TAVILY_API_KEY
    if not api_key:
        return "Tavily search is not configured. Please set the environment variable TAVILY_API_KEY."

    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
            },
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        return f"Tavily search failed. Error: {str(e)}"

    results = payload.get("results") or []
    if not results:
        return "No web results found matching the query."

    formatted_results = []
    for i, r in enumerate(results):
        title = r.get("title", "").strip()
        url = (r.get("url") or "").strip()
        content = (r.get("content") or "").strip()
        formatted_results.append(
            f"[{i+1}] Title: {title}\nURL: {url}\nContent: {content}"
        )

    return "## Sources\n\n" + "\n\n".join(formatted_results)


class AACRSearchInput(BaseModel):
    query: str = Field(
        description="The semantic search query (e.g., 'novel KRAS inhibitors')."
    )
    filter_expr: Optional[str] = Field(
        default=None,
        description=(
            "Optional Vertex AI Search filter expression. Use ONLY when the user requests a time window "
            "or a specific issue. Supported fields: 'publicationDate' (format: \"YYYY-MM-DD\") and 'issue'. "
            "Examples: publicationDate >= \"2020-01-01\" AND publicationDate <= \"2025-12-31\"; "
            "issue: ANY(\"Supplement\")"
        ),
    )
    only_annual_meeting: bool = Field(
        default=False,
        description="Set to True ONLY if the user specifically requests information from annual meetings",
    )


class VertexSearchRestRetriever(BaseRetriever):
    """Vertex AI Search retriever using REST transport (no gRPC)."""

    project_id: str
    location_id: str
    data_store_id: str
    max_documents: int = 50
    filter: Optional[str] = None

    def __init__(
        self,
        project_id: str,
        location_id: str,
        data_store_id: str,
        max_documents: int = 50,
        **kwargs,
    ):
        super().__init__(
            project_id=project_id,
            location_id=location_id,
            data_store_id=data_store_id,
            max_documents=max_documents,
            **kwargs,
        )
        self._client = discoveryengine.SearchServiceClient(transport="rest")
        self._serving_config = (
            f"projects/{project_id}/locations/{location_id}/collections/default_collection/"
            f"dataStores/{data_store_id}/servingConfigs/default_config"
        )

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> List[Document]:
        request = discoveryengine.SearchRequest(
            serving_config=self._serving_config,
            query=query,
            filter=self.filter,
            page_size=self.max_documents,
            content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                    return_snippet=True
                ),
                extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_answer_count=1
                ),
            ),
        )
        resp = self._client.search(request=request)
        return resp.results


@tool("search_aacr_abstracts", args_schema=AACRSearchInput)
def search_aacr_abstracts(
    query: str, filter_expr: Optional[str] = None, only_annual_meeting: bool = False
) -> str:
    """
    Searches and retrieves publication abstracts from the American Association for Cancer Research (AACR). Use this tool to find scientific studies, clinical trial summaries, and research findings related to oncology, tumor biology, and cancer treatments. Input should be a specific search query containing medical terms, cancer types (e.g., NSCLC, breast cancer), gene names (e.g., BRCA1, KRAS), or specific therapies.
    """
    _require_runtime_config()

    retriever = VertexSearchRestRetriever(
        project_id=PROJECT_ID,
        location_id=LOCATION,
        data_store_id=DATA_STORE_ID,
        max_documents=10,
        filter=filter_expr,
    )

    try:
        docs = retriever.invoke(query)
    except Exception as e:
        return f"Search failed. Please check your filter syntax. Error: {str(e)}"

    if not docs:
        return "No relevant abstracts found matching the query and filter."

    formatted_results = []
    for i, result in enumerate(docs):
        doc_dict = type(result.document).to_dict(result.document)
        struct = doc_dict.get("struct_data", {})
        title = struct.get("title", "")
        pub_date = struct.get("publicationDate", "")
        issue = struct.get("issue", "")
        url = struct.get("URL", "") or struct.get("url", "")
        doi = struct.get("DOI", "") or struct.get("doi", "")
        raw_abstract = struct.get("abstract", "")
        abstract = _strip_jats(raw_abstract) if raw_abstract else title
        if only_annual_meeting:
            is_am = "annual meeting" in abstract.lower() or ".am" in doi.lower()
            if not is_am:
                continue
        ref = url or (f"https://doi.org/{doi}" if doi else "")

        result_str = (
            f"[{i+1}] Title: {title}\n"
            f"Publication Date: {pub_date}\n"
            f"Issue: {issue}\n"
            f"Reference: {ref}\n"
            f"Abstract: {abstract}\n"
        )
        formatted_results.append(result_str)

    return "## Sources\n\n" + "\n\n".join(formatted_results)
