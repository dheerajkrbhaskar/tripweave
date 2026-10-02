"""Deterministic routing rules for the TripWeave graph."""

from typing import Callable

from agents.supervisor import AGENT_ORDER
from graph.state import TravelState


ROUTE_MAP = {
    "guardrail_blocked": "guardrail_blocked",
    "final_agent": "final_agent",
    **{agent: agent for agent in AGENT_ORDER},
}


def selected_agents(state: TravelState) -> list[str]:
    selected = state.get("selected_agents", [])
    return [agent for agent in AGENT_ORDER if agent in selected]


def route_from_supervisor(state: TravelState) -> str:
    if not state.get("guardrail_allowed", True):
        return "guardrail_blocked"
    selected = selected_agents(state)
    return selected[0] if selected else "final_agent"


def route_after_agent(current_agent: str) -> Callable[[TravelState], str]:
    def route(state: TravelState) -> str:
        current_index = AGENT_ORDER.index(current_agent)
        selected = selected_agents(state)
        for next_agent in AGENT_ORDER[current_index + 1:]:
            if next_agent in selected:
                return next_agent
        return "final_agent"
    return route


def route_after_itinerary(state: TravelState) -> str:
    _ = state
    return "human_approval"
