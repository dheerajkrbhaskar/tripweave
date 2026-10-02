"""Itinerary generation and human-approval agent."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from agents.common import constraint_context, empty_scope, llm, log_prompt_metrics, prompt_text
from graph.state import TravelState


def itinerary_agent(state: TravelState) -> dict[str, Any]:
    scope = state.get("requested_scope", empty_scope())
    prompt = f"""Create only the itinerary or trip plan requested by the user.
Do not add unrelated hotels, flights, weather, budget, visa, restaurant,
or activity sections unless they are explicitly in the requested scope.
Requested scope: {scope}
User Query: {prompt_text(state['user_query'], 1200)}
Trip Constraints:
{constraint_context(state)}
Constraint warnings: {state.get('constraint_warnings', [])}
Flight Results: {prompt_text(state.get('flight_results', ''), 2200)}
Hotel Results: {prompt_text(state.get('hotel_results', ''), 1400)}
Weather Results: {prompt_text(state.get('weather_results', ''), 1600)}
Budget Results: {prompt_text(state.get('budget_results', ''), 3200)}

Respect the requested duration, budget, destination, travel style, and
preferences. If requirements conflict, explain the tradeoff instead of
silently changing them. Use only available information, preserve useful facts,
label estimates, and keep it practical and under 1,500 words. Do not reproduce
incomplete source fragments. This is a draft for human review."""
    log_prompt_metrics("itinerary_agent", prompt, state)
    response = llm.invoke(
        [SystemMessage(content="You are an expert travel planner."), HumanMessage(content=prompt)]
    )
    return {
        "itinerary": response.content,
        "approval_request": "Approve it to create the final plan, or provide feedback for revision.",
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def human_approval_agent(state: TravelState) -> dict[str, Any]:
    review = interrupt({
        "question": "Do you approve this itinerary?",
        "draft_itinerary": state.get("itinerary", ""),
        "approval_request": state.get("approval_request", ""),
        "selected_agents": state.get("selected_agents", []),
        "trip_constraints": state.get("trip_constraints", {}),
        "constraint_warnings": state.get("constraint_warnings", []),
        "expected_response": {"approved": True, "feedback": "Optional revision feedback"},
    })
    if not isinstance(review, dict):
        raise ValueError("Human approval must be an object.")
    return {
        "approved": bool(review.get("approved", False)),
        "human_feedback": str(review.get("feedback", "")).strip(),
    }
