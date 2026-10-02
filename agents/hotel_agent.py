"""Hotel and accommodation specialist agent."""

import asyncio
from typing import Any

from mcp_client import tavily_mcp_search
from agents.common import constraint_context
from graph.state import TravelState


def hotel_agent(state: TravelState) -> dict[str, Any]:
    query = (
        f"Find accommodation for this request:\n{state['user_query']}\n"
        f"Constraints:\n{constraint_context(state)}"
    )
    try:
        hotel_results = asyncio.run(tavily_mcp_search(query))
    except Exception as exc:
        print(f"Hotel MCP error: {type(exc).__name__}: {exc}", flush=True)
        hotel_results = (
            "Live hotel search is temporarily unavailable. Provide general "
            "accommodation guidance and clearly label it as non-live advice."
        )
    return {"hotel_results": hotel_results, "llm_calls": state.get("llm_calls", 0)}
