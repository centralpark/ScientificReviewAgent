import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# LangChain / Google Cloud imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

# LangGraph imports
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

repo_root = Path(__file__).resolve().parents[3]  # research_agent/
sys.path.insert(0, str(repo_root))

from tools import compute_date, search_aacr_abstracts, tavily_web_search

# -------------------------------------------------------------------
# 1. Setup the Retriever for Vertex AI Data Store (REST, no gRPC)
# -------------------------------------------------------------------
load_dotenv(override=False)

PROJECT_ID = os.environ.get("PROJECT_ID")
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



tools = [search_aacr_abstracts, compute_date, tavily_web_search]


def build_agent_app():
    """Build and compile the LangGraph agent (import-safe)."""
    _require_runtime_config()
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.1-pro-preview",
        temperature=1.0,
        google_api_key=GOOGLE_API_KEY,
        project=PROJECT_ID,
        thinking_level="high",
    )
    llm_with_tools = llm.bind_tools(tools)

    # -------------------------------------------------------------------
    # 4. Define the LangGraph Nodes and State
    # -------------------------------------------------------------------
    # We use the prebuilt MessagesState which holds a list of messages
    def literature_agent(state: MessagesState):
        """The agent node calls the LLM with the current conversation history."""
        citation_instructions = SystemMessage(content=prompt.MEDICAL_EVAL_PROMPT)
        response = llm_with_tools.invoke([citation_instructions, *state["messages"]])
        # Return the new message to be appended to the state
        return {"messages": [response]}

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
    # user_query = "Summarize the studies that demonstrate effective treatment for pre-cancerous lesion, published in the last 3 years. Only include information from AACR annual meetings."

    user_query = """
    What are the effects (either positive or negative) of SIRT3 over-expression in Osteoarthritis? Structure your response strictly by the strength of evidence in the following descending order:
    1. Clinical/Human Cohort data
    2. In Vivo (Animal models)
    3. In Vitro (Cell lines/organoids).
    research evaluation
    """

    # Initialize the state with the user's message
    inputs = {"messages": [HumanMessage(content=user_query)]}

    app.invoke(inputs)