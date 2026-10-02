"""Weather specialist agent."""

import asyncio
from typing import Any

from mcp_client import extract_destination, forecast_mcp_search, weather_mcp_search
from graph.state import TravelState


def weather_agent(state: TravelState) -> dict[str, Any]:
    constraints = state.get("trip_constraints", {})
    city = constraints.get("destination") or extract_destination(state["user_query"])
    try:
        weather_data = asyncio.run(weather_mcp_search(city))
        forecast_data = asyncio.run(forecast_mcp_search(city))
        weather_results = f"Current Weather:\n{weather_data}\n\nForecast:\n{forecast_data}"
    except Exception as exc:
        print(f"Weather MCP error: {type(exc).__name__}: {exc}", flush=True)
        weather_results = (
            f"Live weather information for {city} is temporarily unavailable. "
            "Give general seasonal guidance and advise verifying the forecast."
        )
    return {"weather_results": weather_results}
