"""Compatibility-facing workflow runners for the FastAPI application."""

import uuid
from typing import Any

from langgraph.types import Command

from agents.common import empty_scope
from graph.workflow import travel_graph


def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return None
    first = interrupts[0]
    payload = getattr(first, "value", first)
    return payload if isinstance(payload, dict) else {"value": payload}


def _serialize_result(result: dict[str, Any], thread_id: str) -> dict[str, Any]:
    interrupt_payload = _interrupt_payload(result)
    itinerary = (
        interrupt_payload.get("draft_itinerary", "")
        if interrupt_payload
        else result.get("itinerary", "")
    )
    return {
        "thread_id": thread_id,
        "answer": result.get("final_answer", "") or itinerary,
        "requires_approval": interrupt_payload is not None,
        "approval_request": (
            interrupt_payload.get("approval_request", "")
            if interrupt_payload
            else result.get("approval_request", "")
        ),
        "itinerary": itinerary,
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "weather_results": result.get("weather_results", ""),
        "budget_results": result.get("budget_results", ""),
        "selected_agents": result.get("selected_agents", []),
        "requested_scope": result.get("requested_scope", empty_scope()),
        "trip_constraints": result.get("trip_constraints", {}),
        "constraint_warnings": result.get("constraint_warnings", []),
        "supervisor_reasoning": result.get("supervisor_reasoning", ""),
        "guardrail_allowed": result.get("guardrail_allowed", True),
        "guardrail_reason": result.get("guardrail_reason", ""),
        "approved": result.get("approved"),
        "human_feedback": result.get("human_feedback", ""),
        "llm_calls": result.get("llm_calls", 0),
    }


def run_travel_agent(user_input: str, thread_id: str | None = None) -> dict[str, Any]:
    thread_id = thread_id or f"user_{uuid.uuid4().hex}"
    result = travel_graph.invoke(
        {
            "user_query": user_input,
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "itinerary": "",
            "final_answer": "",
            "budget_results": "",
            "requested_scope": empty_scope(),
            "constraint_warnings": [],
            "llm_calls": 0,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    return _serialize_result(result, thread_id)


def resume_travel_agent(thread_id: str, approved: bool, feedback: str = "") -> dict[str, Any]:
    result = travel_graph.invoke(
        Command(resume={"approved": approved, "feedback": feedback}),
        config={"configurable": {"thread_id": thread_id}},
    )
    return _serialize_result(result, thread_id)
