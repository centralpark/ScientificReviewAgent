from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage, AIMessage, SystemMessage

system_msg = SystemMessage("You are a helpful assistant.")
human_msg = HumanMessage("Hello, how are you?")

# Use with chat models
messages = [system_msg, human_msg]
response = model.invoke(messages)  # Returns AIMessage


messages = [
    SystemMessage("You are a poetry expert"),
    HumanMessage("Write a haiku about spring"),
    AIMessage("Cherry blossoms bloom...")
]
response = model.invoke(messages)



system_msg = SystemMessage("""
You are a senior Python developer with expertise in web frameworks.
Always provide code examples and explain your reasoning.
Be concise but thorough in your explanations.
""")

messages = [
    system_msg,
    HumanMessage("How do I create a REST API?")
]
response = model.invoke(messages)

# Best default
md = response.content
print(md)  # terminal with plain newlines



# Create an AI message manually (e.g., for conversation history)
ai_msg = AIMessage("I'd be happy to help you with that question!")

# Add to conversation history
messages = [
    SystemMessage("You are a helpful assistant"),
    HumanMessage("Can you help me?"),
    ai_msg,  # Insert as if it came from the model
    HumanMessage("Great! What's 2+2?")
]

response = model.invoke(messages)
print(response.content)



def get_weather(location: str) -> str:
    """Get the weather at a location."""
    ...

model_with_tools = model.bind_tools([get_weather])
response = model_with_tools.invoke("What's the weather in Paris?")

for tool_call in response.tool_calls:
    print(f"Tool: {tool_call['name']}")
    print(f"Args: {tool_call['args']}")
    print(f"ID: {tool_call['id']}")



from langchain_community.tools.pubmed.tool import PubmedQueryRun
from langchain_community.utilities.pubmed import PubMedAPIWrapper
tool = PubmedQueryRun(api_wrapper=PubMedAPIWrapper(top_k_results=5, doc_content_chars_max=10000))
response = tool.invoke("adverse effects of SIRT3 overexpression")
print(response)



from dotenv import load_dotenv
load_dotenv(override=False)

from langchain.agents import create_agent


def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"


agent = create_agent(
    model="gpt-5-nano",
    tools=[get_weather],
    system_prompt="You are a helpful assistant",
)

# Run the agent
agent.invoke(
    {"messages": [{"role": "user", "content": "What is the weather in San Francisco?"}]}
)


from pydantic import BaseModel, Field
from langchain.agents import create_agent


class ContactInfo(BaseModel):
    """Contact information for a person."""
    name: str = Field(description="The name of the person")
    email: str = Field(description="The email address of the person")
    phone: str = Field(description="The phone number of the person")

agent = create_agent(
    model="gemini-3-flash-preview",
    response_format=ContactInfo  # Auto-selects ProviderStrategy
)

result = agent.invoke({
    "messages": [{"role": "user", "content": "Extract contact info from: John Doe, john@example.com, (555) 123-4567"}]
})

print(result["structured_response"])
# ContactInfo(name='John Doe', email='john@example.com', phone='(555) 123-4567')


from dotenv import load_dotenv

import os
load_dotenv(override=False)

from langchain_google_genai import ChatGoogleGenerativeAI

PROJECT_ID = os.environ.get("PROJECT_ID")
LOCATION = "global"
DATA_STORE_ID = os.environ.get("DATA_STORE_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")


llm = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview",
        temperature=1.0,
        google_api_key=GOOGLE_API_KEY,
        project=PROJECT_ID
    )

structured = llm.with_structured_output(ContactInfo, method="json_schema")
response = structured.invoke("Extract contact info from: John Doe, john@example.com, (555) 123-4567")
print(response)