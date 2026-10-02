"""Guardrail and request-aware supervisor agent."""

from typing import Any

from agents.common import empty_constraints, empty_scope, json_from_llm, llm_text
from graph.state import TravelState

KNOWN_AGENTS = {"flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"}
AGENT_ORDER = ["flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"]


def infer_request_scope(query: str) -> dict[str, bool]:
    text = query.lower()
    scope = empty_scope()
    scope["flight"] = any(term in text for term in ("flight", "airfare", "airline", "airport", "route", "departure", "arrival"))
    scope["hotel"] = any(term in text for term in ("hotel", "accommodation", "lodging", "where to stay", "stay in"))
    scope["weather"] = any(term in text for term in ("weather", "forecast", "climate", "temperature", "rainfall")) or ("packing" in text and "weather" in text)
    scope["budget"] = any(term in text for term in ("budget", "afford", "how much", "total cost", "trip cost", "expenses"))
    explicit_limit = any(term in text for term in ("under ₹", "under rs", "under inr"))
    scope["budget"] = scope["budget"] or (explicit_limit and any(term in text for term in ("trip", "travel", "cost")))
    scope["itinerary"] = any(term in text for term in ("itinerary", "day-by-day", "day by day", "schedule", "plan my trip", "plan a ", "complete travel plan"))
    if scope["itinerary"] and any(phrase in text for phrase in ("already booked", "booked my flight", "booked my hotel")):
        scope["flight"] = False
        scope["hotel"] = False
    if scope["budget"] and any(phrase in text for phrase in ("can i travel", "trip cost", "total cost", "how much")):
        scope["flight"] = scope["flight"] or "flight" not in text
        scope["hotel"] = scope["hotel"] or "hotel" not in text
    return scope


def agents_from_scope(scope: dict[str, bool]) -> list[str]:
    return [agent for agent in AGENT_ORDER if scope.get(agent.removesuffix("_agent"), False)]


def supervisor_agent(state: TravelState) -> dict[str, Any]:
    query = state["user_query"]
    llm_calls = state.get("llm_calls", 0)
    guardrail_prompt = f"""Determine whether this request is travel planning or travel information.
Allow flights, hotels, destinations, weather, budgets, transportation,
sightseeing, food, packing, and itineraries. Reject clearly unrelated,
harmful, or illegal requests. Missing trip details are allowed.

Return strict JSON only: {{"allowed": true, "reason": ""}}

User request:
{query}"""
    try:
        guardrail = json_from_llm(llm_text("You are a lightweight travel input guardrail. Return strict JSON only.", guardrail_prompt))
        allowed = bool(guardrail.get("allowed", True))
        reason = str(guardrail.get("reason", "")).strip()
        llm_calls += 1
    except Exception as exc:
        print(f"Guardrail fallback used: {type(exc).__name__}: {exc}")
        allowed = True
        reason = "Guardrail validation fallback allowed the request."

    if not allowed:
        reason = reason or "This assistant can only help with travel-planning requests. Ask about a destination, flight, hotel, weather, budget, or itinerary."
        return {
            "guardrail_allowed": False, "guardrail_reason": reason,
            "selected_agents": [], "requested_scope": empty_scope(),
            "constraint_warnings": [], "trip_constraints": empty_constraints(),
            "supervisor_reasoning": reason, "final_answer": reason,
            "llm_calls": llm_calls,
        }

    prompt = f"""Select the minimum specialist agents needed for the user's actual request.
Do not select an agent merely because the request is travel-related.
Available agents:
- flight_agent: flights, prices, airfare, airlines, airports, routes, or duration
- hotel_agent: hotels, accommodation, lodging, neighborhoods, or where to stay
- weather_agent: weather, forecast, climate, temperature, rainfall, or weather packing
- budget_agent: total cost, affordability, budget limits, cost comparison, or feasibility
- itinerary_agent: an explicitly requested itinerary, schedule, day-by-day plan, or complete trip plan

The itinerary agent is NOT required for a simple information request.
The budget agent is NOT required just because a price appears in another request.
Choose the minimum sufficient workflow.

Return strict JSON only with this shape:
{{"selected_agents": ["flight_agent"], "requested_scope": {{"flight": true, "hotel": false, "weather": false, "budget": false, "itinerary": false}}, "trip_constraints": {{"destination": "", "origin": "", "duration": "", "budget": "", "travel_style": "", "special_preferences": []}}, "reasoning": ""}}

User request:
{query}"""
    try:
        parsed = json_from_llm(llm_text("You route work to known travel specialist agents. Return strict JSON only.", prompt))
        requested_agents = parsed.get("selected_agents", [])
        if not isinstance(requested_agents, list):
            raise ValueError("selected_agents must be a list.")
        selected_agents = [name for name in AGENT_ORDER if name in requested_agents and name in KNOWN_AGENTS]
        requested_scope = empty_scope()
        parsed_scope = parsed.get("requested_scope", {})
        if isinstance(parsed_scope, dict):
            for key in requested_scope:
                requested_scope[key] = bool(parsed_scope.get(key, False))
        if not any(requested_scope.values()):
            for agent in selected_agents:
                requested_scope[agent.removesuffix("_agent")] = True
        selected_agents = [agent for agent in AGENT_ORDER if agent in selected_agents and requested_scope.get(agent.removesuffix("_agent"), False)]
        for agent in agents_from_scope(requested_scope):
            if agent not in selected_agents:
                selected_agents.append(agent)
        constraints = empty_constraints()
        parsed_constraints = parsed.get("trip_constraints", {})
        if isinstance(parsed_constraints, dict):
            for key in constraints:
                if key in parsed_constraints:
                    constraints[key] = parsed_constraints[key]
        reasoning = str(parsed.get("reasoning", "")).strip()
        llm_calls += 1
    except Exception as exc:
        print(f"Supervisor fallback used: {type(exc).__name__}: {exc}")
        requested_scope = infer_request_scope(query)
        selected_agents = agents_from_scope(requested_scope)
        constraints = empty_constraints()
        reasoning = "Supervisor parsing failed, so a conservative keyword-based scope was selected as a safe fallback."
    return {
        "guardrail_allowed": True, "guardrail_reason": reason,
        "selected_agents": selected_agents, "requested_scope": requested_scope,
        "trip_constraints": constraints, "supervisor_reasoning": reasoning,
        "llm_calls": llm_calls,
    }


def guardrail_blocked_agent(state: TravelState) -> dict[str, str]:
    return {"final_answer": state.get("guardrail_reason", "This request was blocked by the travel input guardrail.")}
