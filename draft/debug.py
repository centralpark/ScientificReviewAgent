import os
from dotenv import load_dotenv

# Load local environment variables from .env before importing the agent.
load_dotenv(override=False)

PROJECT_ID = os.environ.get("PROJECT_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

from langchain_google_genai import ChatGoogleGenerativeAI

model = ChatGoogleGenerativeAI(model="gemini-3.1-pro-preview", temperature=1.0, google_api_key=GOOGLE_API_KEY, project=PROJECT_ID)