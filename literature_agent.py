import os
import re
from typing import List, Optional

from pydantic import BaseModel, Field

# LangChain / Google Cloud imports
from langchain_core.tools.retriever import create_retriever_tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from google.cloud import discoveryengine_v1 as discoveryengine

# LangGraph imports
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition


def _strip_jats(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Define the Input Schema so the LLM knows how to filter
class AACRSearchInput(BaseModel):
    query: str = Field(
        description="The semantic search query (e.g., 'novel KRAS inhibitors')."
    )
    filter_expr: Optional[str] = Field(
        default=None,
        description=(
            "Optional Vertex AI Search filter expression. ONLY use this if the user asks for "
            "a specific year or journal. Available fields: 'publicationDate', 'container-title'. "
            "Syntax must be exactly like: publicationDate >= \"2020-01-01\" OR "
            "container-title = \"Cancer Research\""
        )
    )


class VertexSearchRestRetriever(BaseRetriever):
    """Vertex AI Search retriever using REST transport (no gRPC)."""

    project_id: str
    location_id: str
    data_store_id: str
    max_documents: int = 10
    filter: Optional[str] = None

    def __init__(
        self,
        project_id: str,
        location_id: str,
        data_store_id: str,
        max_documents: int = 10,
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
        docs: List[Document] = []
        for result in resp.results:
            doc_dict = type(result.document).to_dict(result.document)
            struct = (doc_dict or {}).get("struct_data") or doc_dict
            abstract = struct.get("abstract", "")
            page_content = _strip_jats(abstract) if abstract else struct.get("title", "")
            docs.append(Document(page_content=page_content or "", metadata=dict(struct)))
        return docs


@tool("search_aacr_abstracts", args_schema=AACRSearchInput)
def search_aacr_abstracts(query: str, filter_expr: Optional[str] = None) -> str:
    """
    Searches and retrieves publication abstracts from the American Association for Cancer Research (AACR). Use this tool to find scientific studies, clinical trial summaries, and research findings related to oncology, tumor biology, and cancer treatments. Input should be a specific search query containing medical terms, cancer types (e.g., NSCLC, breast cancer), gene names (e.g., BRCA1, KRAS), or specific therapies.
    """
    
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
    formatted_results =[]
    for i, doc in enumerate(docs):
        meta = doc.metadata
        title = meta.get('title', 'Unknown Title')
        pub_date = meta.get('publicationDate', 'Unknown Date')
        raw_abstract = meta.get('abstract', 'No abstract available')
        
        # Clean XML tags
        clean_abstract = re.sub(r'<[^>]+>', ' ', raw_abstract)
        clean_abstract = re.sub(r'\s+', ' ', clean_abstract).strip()
        
        result_str = (
            f"--- Document {i+1} ---\n"
            f"Title: {title}\n"
            f"Date: {pub_date}\n"
            f"Abstract: {clean_abstract}\n"
        )
        formatted_results.append(result_str)
        
    return "\n\n".join(formatted_results)


# -------------------------------------------------------------------
# 1. Setup the Retriever for Vertex AI Data Store (REST, no gRPC)
# -------------------------------------------------------------------
PROJECT_ID = os.environ.get("PROJECT_ID", "llm-app-488813")
LOCATION = "global"
DATA_STORE_ID = os.environ.get("DATA_STORE_ID", "aacr-abstracts_1773385412104")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyCE0kuDV_t2ZuASgFqFPaw7MsuZh9E0DMo")

retriever = VertexSearchRestRetriever(
    project_id=PROJECT_ID,
    location_id=LOCATION,
    data_store_id=DATA_STORE_ID,
    max_documents=10,
)


# -------------------------------------------------------------------
# 2. Create the RAG Tool
# -------------------------------------------------------------------
# Wrap the retriever into a tool that the LLM can invoke
rag_tool = create_retriever_tool(
    retriever,
    name="search_aacr_abstracts",
    description="Searches and retrieves publication abstracts from the American Association for Cancer Research (AACR). Use this tool to find scientific studies, clinical trial summaries, and research findings related to oncology, tumor biology, and cancer treatments. Input should be a specific search query containing medical terms, cancer types (e.g., NSCLC, breast cancer), gene names (e.g., BRCA1, KRAS), or specific therapies."
)

# Test the retriever
user_query = "Summarize the studies that focus on pre-cancerous lesion."
results = retriever.invoke(user_query)
results_2 = rag_tool.invoke(user_query)

tools = [rag_tool]

# -------------------------------------------------------------------
# 3. Setup the LLM and Bind Tools
# -------------------------------------------------------------------
# Use Gemini 1.5 Pro or Flash as the reasoning engine
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
    response = llm_with_tools.invoke(state["messages"])
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
app = workflow.compile()

# -------------------------------------------------------------------
# 6. test part
# -------------------------------------------------------------------

user_query = "Summarize the studies that focus on pre-cancerous lesion."
retriever.invoke(user_query)

# Initialize the state with the user's message
inputs = {"messages": [HumanMessage(content=user_query)]}

# Stream the events from the graph
for event in app.stream(inputs, stream_mode="values"):
    last_message = event["messages"][-1]
    last_message.pretty_print()