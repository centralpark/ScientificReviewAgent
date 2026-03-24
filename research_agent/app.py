import os
import json

import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from dotenv import load_dotenv

# Load local environment variables from .env before importing the agent.
load_dotenv(override=False)

# Import your compiled LangGraph workflow
from research_agent.agent import app as agent_app

st.set_page_config(page_title="Pharmaceutical Research Assistant", page_icon="🧬")
st.title("Pharmaceutical Research Assistant")


# --- NEW HELPER FUNCTION ---
def extract_text(message) -> str:
    """Robustly extracts text from LangChain messages, handling Gemini's list format."""
    if isinstance(message.content, list):
        # Extract and join only the blocks that are type "text"
        text = "".join(
            block["text"]
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        text = str(message.content)

    text = text.replace("\\n", "\n")
    text = text.replace("\n", "  \n")

    return text


# ---------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display previous chat messages
for msg in st.session_state.messages:
    role = "user" if isinstance(msg, HumanMessage) else "assistant"
    with st.chat_message(role):
        # Use our helper function and explicitly render as markdown
        st.markdown(extract_text(msg))

# Accept user input
if prompt := st.chat_input("Ask about cancer research..."):
    user_message = HumanMessage(content=prompt)
    st.session_state.messages.append(user_message)

    with st.chat_message("user"):
        st.markdown(prompt)

    # Call the LangGraph agent
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            inputs = {"messages": st.session_state.messages}

            # Execute the graph
            result = agent_app.invoke(inputs)

            # Get the final AIMessage
            final_message = result["messages"][-1]

            # Extract the actual string and render it as Markdown
            answer_text = extract_text(final_message)
            st.markdown(answer_text)

            # Save the raw agent's response object to history so the Graph maintains context
            st.session_state.messages.append(final_message)
