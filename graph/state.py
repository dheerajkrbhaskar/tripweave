"""Shared state passed between TripWeave graph nodes."""

from typing import Any, TypedDict


class TravelState(TypedDict, total=False):
    user_query: str
    flight_results: str
    hotel_results: str
    weather_results: str
    itinerary: str
    final_answer: str
    budget_results: str
    constraint_warnings: list[str]
    guardrail_allowed: bool
    guardrail_reason: str
    selected_agents: list[str]
    requested_scope: dict[str, bool]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str
    approval_request: str
    approved: bool
    human_feedback: str
    llm_calls: int
