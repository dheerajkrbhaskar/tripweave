"""Flight specialist agent."""

import asyncio
from typing import Any

from mcp_client import flight_mcp_search
from graph.state import TravelState


def flight_agent(state: TravelState) -> dict[str, Any]:
    constraints = state.get("trip_constraints", {})
    route_query = (
        f"{constraints.get('origin', '')} to {constraints.get('destination', '')}"
        if constraints.get("origin") or constraints.get("destination")
        else state["user_query"]
    )
    return {
        "flight_results": asyncio.run(flight_mcp_search(route_query)),
        "llm_calls": state.get("llm_calls", 0) + 1,
    }
