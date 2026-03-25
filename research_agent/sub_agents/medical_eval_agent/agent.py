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

from research_agent.report_schema import AgentReport, AgentType
from research_agent.reporting import (
    build_agent_report_from_markdown,
    extract_text,
    save_report_outputs,
)
from tools import tavily_web_search
import research_agent.sub_agents.medical_eval_agent.prompt as prompt

# -------------------------------------------------------------------
# 1. Setup the Retriever for Vertex AI Data Store (REST, no gRPC)
# -------------------------------------------------------------------
load_dotenv(override=False)

PROJECT_ID = os.environ.get("PROJECT_ID")
DATA_STORE_ID = os.environ.get("DATA_STORE_ID")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")


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

tools = [tavily_web_search]


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
    def medical_eval_agent(state: MessagesState):
        """The agent node calls the LLM with the current conversation history."""
        medical_eval_instructions = SystemMessage(content=prompt.MEDICAL_EVAL_PROMPT)
        response = llm_with_tools.invoke([medical_eval_instructions, *state["messages"]])
        # Return the new message to be appended to the state
        return {"messages": [response]}

    # -------------------------------------------------------------------
    # 5. Build and Compile the Graph
    # -------------------------------------------------------------------
    workflow = StateGraph(MessagesState)

    # Add our reasoning node and the prebuilt ToolNode
    workflow.add_node("medical_eval_agent", medical_eval_agent)
    workflow.add_node("tools", ToolNode(tools))

    # Define the flow
    workflow.add_edge(START, "medical_eval_agent")

    # tools_condition checks if the LLM returned tool_calls.
    # If yes -> goes to "tools" node. If no -> goes to END.
    workflow.add_conditional_edges("medical_eval_agent", tools_condition)

    # After tools are executed, return to the agent to synthesize the answer
    workflow.add_edge("tools", "medical_eval_agent")

    # Compile into a runnable application
    return workflow.compile()


app = build_agent_app()
MODEL_NAME = "gemini-3.1-pro-preview"


def run_markdown_report(query: str) -> str:
    inputs = {"messages": [HumanMessage(content=query)]}
    result = app.invoke(inputs)
    final_message = result["messages"][-1]
    return extract_text(final_message)


def run_structured_report(
    query: str,
    *,
    target: str | None = None,
    indication: str | None = None,
    markdown_path: str | Path | None = None,
    json_path: str | Path | None = None,
) -> AgentReport:
    markdown_text = run_markdown_report(query)
    report = build_agent_report_from_markdown(
        markdown_text,
        agent_type=AgentType.MEDICAL_EVAL,
        query=query,
        target=target,
        indication=indication,
        model_name=MODEL_NAME,
        source_markdown_file=str(markdown_path) if markdown_path is not None else None,
    )
    save_report_outputs(
        report,
        markdown_text,
        markdown_path=markdown_path,
        json_path=json_path,
    )
    return report


# -------------------------------------------------------------------
# 6. test part
# -------------------------------------------------------------------

if __name__ == "__main__":
    # user_query = "Summarize the studies that demonstrate effective treatment for pre-cancerous lesion, published in the last 3 years. Only include information from AACR annual meetings."

    user_query = """
    Evaluate the medical value of COL17A and SIRT3 for the treatment of Osteoarthritis.
    """

    report = run_structured_report(
        user_query,
        indication="Osteoarthritis",
        markdown_path=repo_root / "draft" / "medical_eval_report.md",
        json_path=repo_root / "draft" / "medical_eval_report.json",
    )
    print(report.model_dump_json(indent=2))
