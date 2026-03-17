import os
from typing import Annotated, TypedDict

# LangChain / Google Cloud imports
from langchain_google_community import VertexAISearchRetriever
from langchain_core.tools.retriever import create_retriever_tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

# LangGraph imports
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

# -------------------------------------------------------------------
# 1. Setup the Retriever for Vertex AI Data Store
# -------------------------------------------------------------------
PROJECT_ID = os.environ.get("PROJECT_ID", "llm-app-488813")
LOCATION = "global"
DATA_STORE_ID = os.environ.get("DATA_STORE_ID", "aacr-abstracts_1773385412104")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyCE0kuDV_t2ZuASgFqFPaw7MsuZh9E0DMo")

# Initialize the Vertex AI Search Retriever
retriever = VertexAISearchRetriever(
    project_id=PROJECT_ID,
    location_id=LOCATION,
    data_store_id=DATA_STORE_ID,
    max_documents=10, # Number of chunks to retrieve
    beta=True,
    engine_data_type=2, # 1 for unstructured, 2 for structured, 3 for website
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

# Initialize the state with the user's message
inputs = {"messages": [HumanMessage(content=user_query)]}

# Stream the events from the graph
for event in app.stream(inputs, stream_mode="values"):
    last_message = event["messages"][-1]
    last_message.pretty_print()