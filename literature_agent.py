import os
import re
import datetime as _dt
from typing import List, Optional

from pydantic import BaseModel, Field
from dotenv import load_dotenv

# LangChain / Google Cloud imports
from langchain_core.tools.retriever import create_retriever_tool
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from google.cloud import discoveryengine_v1 as discoveryengine

# LangGraph imports
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

# -------------------------------------------------------------------
# 1. Setup the Retriever for Vertex AI Data Store (REST, no gRPC)
# -------------------------------------------------------------------
load_dotenv(override=False)

PROJECT_ID = os.environ.get("PROJECT_ID")
LOCATION = "global"
DATA_STORE_ID = os.environ.get("DATA_STORE_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


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

def _years_ago_iso(years: int, months: int = 0, days: int = 0, today: Optional[_dt.date] = None) -> str:
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


# Define the Input Schema so the LLM knows how to filter
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
        )
    )
    only_annual_meeting: bool = Field(
        default=False,
        description="Set to True ONLY if the user specifically requests information from annual meetings"
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
        resp = self._client.search(request=request)

        return resp.results


@tool("search_aacr_abstracts", args_schema=AACRSearchInput)
def search_aacr_abstracts(query: str, filter_expr: Optional[str] = None, only_annual_meeting: bool = False) -> str:
    """
    Searches and retrieves publication abstracts from the American Association for Cancer Research (AACR). Use this tool to find scientific studies, clinical trial summaries, and research findings related to oncology, tumor biology, and cancer treatments. Input should be a specific search query containing medical terms, cancer types (e.g., NSCLC, breast cancer), gene names (e.g., BRCA1, KRAS), or specific therapies.
    """
    
    _require_runtime_config()

    # We instantiate the retriever INSIDE the tool.
    # This is highly recommended for thread-safety in LangGraph so concurrent 
    # user requests don't overwrite each other's filter states.
    retriever = VertexSearchRestRetriever(
        project_id=PROJECT_ID,
        location_id=LOCATION,
        data_store_id=DATA_STORE_ID,
        max_documents=10,
        filter=filter_expr,
    )
    
    # Execute the search
    try:
        docs = retriever.invoke(query)
    except Exception as e:
        return f"Search failed. Please check your filter syntax. Error: {str(e)}"
    
    if not docs:
        return "No relevant abstracts found matching the query and filter."
    
    # -------------------------------------------------------------------
    # 3. Extract and format the metadata (same as before)
    # -------------------------------------------------------------------
    formatted_results = []
    for i, result in enumerate(docs):
        doc_dict = type(result.document).to_dict(result.document)
        struct = doc_dict.get("struct_data", {})
        title = struct.get('title', '')
        pub_date = struct.get('publicationDate', '')
        issue = struct.get("issue", "")
        url = struct.get("URL", "") or struct.get("url", "")
        doi = struct.get("DOI", "") or struct.get("doi", "")
        raw_abstract = struct.get('abstract', '')
        abstract = _strip_jats(raw_abstract) if raw_abstract else title
        # --- THE PYTHON FILTERING LOGIC ---
        if only_annual_meeting:
            # Check if it's actually an annual meeting paper
            is_am = "annual meeting" in abstract.lower() or ".am" in doi.lower()
            
            # If the LLM set the flag, and it's not an AM paper, skip it!
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

tools = [search_aacr_abstracts, compute_date]

def build_agent_app():
    """Build and compile the LangGraph agent (import-safe)."""
    _require_runtime_config()
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.1-pro-preview",
        temperature=1.0,
        google_api_key=GOOGLE_API_KEY,
        project=PROJECT_ID,
        thinking_level="high"
    )
    llm_with_tools = llm.bind_tools(tools)


    # -------------------------------------------------------------------
    # 4. Define the LangGraph Nodes and State
    # -------------------------------------------------------------------
    # We use the prebuilt MessagesState which holds a list of messages
    def literature_agent(state: MessagesState):
        """The agent node calls the LLM with the current conversation history."""
        citation_instructions = SystemMessage(
            content=(
                "When you use information from the tool output, add an inline numeric citation like [1]. "
                "At the end of your answer, add a 'References' section listing ONLY the sources you cited, "
                "one per line, formatted as: [n] <Reference> (prefer URL; if missing, DOI URL). "
                "Do not invent citations or references.\n\n"
                "Time-window filtering:\n"
                "- If the user asks for a relative time window like 'last N years' or 'past N years', "
                "call the tool compute_date(years=N) to compute the cutoff date, then set "
                "filter_expr to: publicationDate >= \"<cutoff>\".\n"
                "- If the user gives an explicit year or date range, construct filter_expr directly."
            )
        )
        response = llm_with_tools.invoke([citation_instructions, *state["messages"]])
        # Return the new message to be appended to the state
        return {"messages":[response]}

    # -------------------------------------------------------------------
    # 5. Build and Compile the Graph
    # -------------------------------------------------------------------
    workflow = StateGraph(MessagesState)

    # Add our reasoning node and the prebuilt ToolNode
    workflow.add_node("literature_agent", literature_agent)
    workflow.add_node("tools", ToolNode(tools))

    # Define the flow
    workflow.add_edge(START, "literature_agent")

    # tools_condition checks if the LLM returned tool_calls.
    # If yes -> goes to "tools" node. If no -> goes to END.
    workflow.add_conditional_edges("literature_agent", tools_condition)

    # After tools are executed, return to the agent to synthesize the answer
    workflow.add_edge("tools", "literature_agent")

    # Compile into a runnable application
    return workflow.compile()

app = build_agent_app()

# -------------------------------------------------------------------
# 6. test part
# -------------------------------------------------------------------

if __name__ == "__main__":

    user_query = "Summarize the studies that demonstrate effective treatment for pre-cancerous lesion, published in the last 3 years. Only include information from AACR annual meetings."

    # Initialize the state with the user's message
    inputs = {"messages": [HumanMessage(content=user_query)]}

    # Stream the events from the graph
    for event in app.stream(inputs, stream_mode="values"):
        last_message = event["messages"][-1]
        last_message.pretty_print()

    # Print final assistant answer (clean text)
    print("\n\nFINAL ANSWER:\n")
    try:
        print(last_message.content)
    except Exception:
        last_message.pretty_print()