import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage

# Import your compiled LangGraph workflow
from literature_agent import app as agent_app 

st.set_page_config(page_title="AACR Research Agent", page_icon="🧬")
st.title("AACR Research Assistant")

# --- NEW HELPER FUNCTION ---
def extract_text(message) -> str:
    """Robustly extracts text from LangChain messages, handling Gemini's list format."""
    if isinstance(message.content, list):
        # Extract and join only the blocks that are type "text"
        return "".join(
            block["text"] for block in message.content 
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(message.content)
# ---------------------------

if "messages" not in st.session_state:
    st.session_state.messages =[]

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
        with st.spinner("Searching AACR database..."):
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