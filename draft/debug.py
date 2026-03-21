import os
from dotenv import load_dotenv

# Load local environment variables from .env before importing the agent.
load_dotenv(override=False)

PROJECT_ID = os.environ.get("PROJECT_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

from langchain_google_genai import ChatGoogleGenerativeAI

model = ChatGoogleGenerativeAI(model="gemini-3.1-pro-preview", temperature=1.0, google_api_key=GOOGLE_API_KEY, project=PROJECT_ID)


conversation = [
    {"role": "system", "content": "You are a helpful assistant that translates English to French."},
    {"role": "user", "content": "Translate: I love programming."},
    {"role": "assistant", "content": "J'adore la programmation."},
    {"role": "user", "content": "Translate: I love building applications."}
]

response = model.invoke(conversation)
print(response)  # AIMessage("J'adore créer des applications.")

for chunk in model.stream("Why do parrots have colorful feathers?"):
    print(chunk.text, end="|", flush=True)


from langchain.tools import tool

@tool
def get_weather(location: str) -> str:
    """Get the weather at a location."""
    return f"It's sunny in {location}."


model_with_tools = model.bind_tools([get_weather])

response = model_with_tools.invoke("What's the weather like in Boston?")
for tool_call in response.tool_calls:
    # View tool calls made by the model
    print(f"Tool: {tool_call['name']}")
    print(f"Args: {tool_call['args']}")


from pydantic import BaseModel, Field

class Movie(BaseModel):
    """A movie with details."""
    title: str = Field(description="The title of the movie")
    year: int = Field(description="The year the movie was released")
    director: str = Field(description="The director of the movie")
    rating: float = Field(description="The movie's rating out of 10")

model_with_structure = model.with_structured_output(Movie)
response = model_with_structure.invoke("Provide details about the movie Inception")
print(response)  # Movie(title="Inception", year=2010, director="Christopher Nolan", rating=8.8)

response = model.invoke("Why do parrots have colorful feathers?")
reasoning_steps = [b for b in response.content_blocks if b["type"] == "reasoning"]
print(" ".join(step["reasoning"] for step in reasoning_steps))



from vertexai.generative_models import GenerativeModel, Tool, grounding

# Give Gemini the power of live Google Search
google_search_tool = Tool.from_google_search_retrieval(grounding.GoogleSearchRetrieval())
model = GenerativeModel("gemini-1.5-pro-001", tools=[google_search_tool])


import os
from langchain_community.tools.tavily_search import TavilySearchResults

# You need a free API key from tavily.com
os.environ["TAVILY_API_KEY"] = "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"

# max_results limits how many websites it scrapes
web_search_tool = TavilySearchResults(max_results=5)
web_search_tool.name = "general_web_search"
web_search_tool.description = "Search the web for up-to-date information, scientific news, and general facts."

import os
from langchain_tavily import TavilySearch

# Ensure your API key is set
os.environ["TAVILY_API_KEY"] = "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"

# Initialize the new TavilySearch tool
web_search_tool = TavilySearch(max_results=5)

# (Optional) You can still customize the name and description for your agent
web_search_tool.name = "general_web_search"
web_search_tool.description = "Search the web for up-to-date information, scientific news, and general facts."

result = web_search_tool.invoke("COL17A protein")