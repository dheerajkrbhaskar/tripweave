import os 
import asyncio
import certifi
import sys
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient


os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
load_dotenv()

TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
AVIATIONSTACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


AVIATION_ENV = os.environ.copy()
AVIATION_ENV.pop("PS1", None)
AVIATION_ENV["AVIATIONSTACK_API_KEY"] = AVIATIONSTACK_API_KEY or ""

WEATHER_ENV = os.environ.copy()
WEATHER_ENV.pop("PS1", None)
WEATHER_ENV["OPENWEATHER_API_KEY"] = OPENWEATHER_API_KEY or ""

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError(
        "GROQ_API_KEY is missing. "
        "Please add it to your .env file."
    )


GROQ_MODEL = os.getenv("GROQ_MODEL")

if not GROQ_MODEL:
    raise ValueError(
        "GROQ_MODEL is missing. "
        "Please add it to your .env file."
    )

llm = ChatGroq(
    model=GROQ_MODEL,
    api_key=GROQ_API_KEY,
)


client = MultiServerMCPClient(
    {
        "tavily":{
            "transport":"streamable_http",
             "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"
        },
        "aviationstack":{
            "transport":"stdio",
            "command":sys.executable,
            "args":[os.path.join(os.path.dirname(__file__), "flight_mcp_server.py")],
            "env": AVIATION_ENV
        },
        "weather":{
            "transport":"stdio",
            "command": ".venv/bin/python",
            "args":["weather_mcp_server.py"],
            "env": WEATHER_ENV
        }
    },
)


tavily_search_tool = None

async def get_tavily_search_tool():
    global tavily_search_tool
    if tavily_search_tool is not None:
        return
    tools= await client.get_tools()

    tavily_search_tool = next(tool for tool in tools if tool.name=="tavily_search")



async def tavily_mcp_search(query:str):
    await get_tavily_search_tool()
    result = await tavily_search_tool.ainvoke({"query":query})

    #print(result)
    return result
async def aviation_mcp_call(tool_name:str, tool_arg:dict=None):
    tools = await client.get_tools()
    tool = next(t for t in tools if t.name == tool_name)
    result = await tool.ainvoke(tool_arg or {})

    return result
    

search_tool =None
aviation_tools = {}
async def initialize_mcp():
    global search_tool
    global aviation_tools
    if search_tool is not None and aviation_tools:
        return
    

    tools = await client.get_tools()
    print("\n Available MCP Tools:\n")

    for tool in tools:
        print(tool.name)

def extract_destination(query:str):
    prompt = f"""Extract only destination city or country.
                Query: {query}
                Return only destination name
                """
    response = llm.invoke(prompt)

    return response.content.strip()

weather_tool = None
forecast_tool = None
flight_tool = None


async def initialize_flight_tools():
    global flight_tool

    if flight_tool is not None:
        return

    tools = await client.get_tools(server_name="aviationstack")
    tools_by_name = {tool.name: tool for tool in tools}
    flight_tool = tools_by_name.get("search_flights_tool")

    if flight_tool is None:
        available_tools = ", ".join(tools_by_name) or "none"
        raise RuntimeError(
            "Missing AviationStack MCP tool: search_flights_tool. "
            f"Available tools: {available_tools}"
        )



async def initialize_weather_tools():
    global weather_tool
    global forecast_tool

    if weather_tool is not None and forecast_tool is not None:
        return

    tools = await client.get_tools(server_name="weather")
    tools_by_name = {tool.name: tool for tool in tools}

    weather_tool = tools_by_name.get("get_current_weather")
    forecast_tool = tools_by_name.get("get_forecast")

    missing_tools = []

    if weather_tool is None:
        missing_tools.append(
            "get_current_weather"
        )

    if forecast_tool is None:
        missing_tools.append(
            "get_forecast"
        )

    if missing_tools:
        available_tools = ", ".join(
            tools_by_name.keys()
        )

        raise RuntimeError(
            "Missing Weather MCP tools: "
            f"{', '.join(missing_tools)}. "
            f"Available tools: "
            f"{available_tools or 'none'}"
        )

async def flight_mcp_search(query:str):
    await initialize_flight_tools()
    result = await flight_tool.ainvoke({"query": query})
    if isinstance(result, list):
        text_parts = [
            item.get("text", "")
            for item in result
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if text_parts:
            return "\n".join(text_parts)
    return str(result)

async def weather_mcp_search(city:str):
    await initialize_weather_tools()
    result = await weather_tool.ainvoke({"city":city})
    return result

async def forecast_mcp_search(city:str):
    await initialize_weather_tools()
    result = await forecast_tool.ainvoke({"city":city})
    return result


if __name__=="__main__":
    #asyncio.run(tavily_mcp_search("introduce yourself"))
    asyncio.run(initialize_mcp()) 