from mcp.server.fastmcp import FastMCP
from tools.flight_tool import search_flights

mcp = FastMCP("Flight MCP Server")

@mcp.tool()
def search_flights_tool(query:str, limit:int=10)->str:
    """
    Search live flight information using AviationStack.

    Args:
        query: Natural-language flight query.
        limit: Maximum number of flights to return.
    """
    return search_flights(query,limit)

if __name__ == "__main__":
    mcp.run(transport="stdio")