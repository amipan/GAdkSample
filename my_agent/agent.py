from google.adk.agents.llm_agent import Agent
from google.adk.tools.google_search_tool import GoogleSearchTool

# Mock tool implementation
def get_current_time(city: str) -> dict:
    """Returns the current time in a specified city."""
    return {"status": "success", "city": city, "time": "10:30 AM"}

root_agent = Agent(
    model='gemini-2.5-flash',
    name='root_agent',
    description="A helpful assistant for user questions",
    instruction="You are a helpful assistant. Answer user questions to the best of your ability.",
    tools=[GoogleSearchTool(bypass_multi_tools_limit=True), get_current_time]
)