import asyncio
import certifi
import json
import os
import uuid
from typing import Any, TypedDict

import psycopg
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg.rows import dict_row

from mcp_client import (
    extract_destination,
    forecast_mcp_search,
    tavily_mcp_search,
    weather_mcp_search,
    flight_mcp_search
)
from tools.flight_tool import search_flights


# ============================================================
# Environment and database configuration
# ============================================================

load_dotenv()
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Please add it to your .env file."
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"
    return database_url


GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing. Please add it to your .env file.")

GROQ_MODEL = os.getenv("GROQ_MODEL")
if not GROQ_MODEL:
    raise ValueError("GROQ_MODEL is missing. Please add it to your .env file.")

llm = ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY)


# ============================================================
# Shared graph state and helpers
# ============================================================

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


KNOWN_AGENTS = {
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
}
AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
]


def estimate_tokens(text: str) -> int:
    """Provide a provider-independent prompt-size estimate for observability."""
    return max(1, len(text) // 4) if text else 0


def log_prompt_metrics(name: str, prompt: str, state: TravelState) -> None:
    print(
        f"{name} prompt: chars={len(prompt)} "
        f"estimated_tokens={estimate_tokens(prompt)} components={{"
        f"'user_query': {len(state.get('user_query', ''))}, "
        f"'flight_results': {len(state.get('flight_results', ''))}, "
        f"'hotel_results': {len(state.get('hotel_results', ''))}, "
        f"'weather_results': {len(state.get('weather_results', ''))}, "
        f"'budget_results': {len(state.get('budget_results', ''))}}}"
    )


def _prompt_text(value: object, limit: int) -> str:
    """Keep accumulated tool output within the provider's prompt budget."""
    text = str(value or "")
    if len(text) <= limit:
        return text
    excerpt = text[:limit]
    boundary = max(
        excerpt.rfind("\n"),
        excerpt.rfind(". "),
        excerpt.rfind(" "),
    )
    if boundary <= 0:
        boundary = limit
    return excerpt[:boundary].rstrip() + "\n[Additional source output omitted]"


def _llm_text(system_prompt: str, user_prompt: str) -> str:
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return str(response.content)


def _json_from_llm(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The model did not return a JSON object.")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("The model returned a JSON value that was not an object.")
    return value


def _empty_constraints() -> dict[str, Any]:
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": [],
    }


def _empty_scope() -> dict[str, bool]:
    return {
        "flight": False,
        "hotel": False,
        "weather": False,
        "budget": False,
        "itinerary": False,
    }


def _constraint_context(state: TravelState) -> str:
    constraints = state.get("trip_constraints", {})
    return (
        f"Destination: {constraints.get('destination') or 'not provided'}\n"
        f"Origin: {constraints.get('origin') or 'not provided'}\n"
        f"Duration: {constraints.get('duration') or 'not provided'}\n"
        f"Budget: {constraints.get('budget') or 'not provided'}\n"
        f"Travel style: {constraints.get('travel_style') or 'not provided'}\n"
        f"Preferences: {constraints.get('special_preferences') or 'none provided'}"
    )


def _detect_constraint_warnings(state: TravelState) -> list[str]:
    query = state.get("user_query", "").lower()
    constraints = state.get("trip_constraints", {})
    warnings: list[str] = []
    budget = str(constraints.get("budget") or "").strip()
    preferences = str(constraints.get("special_preferences") or "").lower()
    if budget and any(term in f"{query} {preferences}" for term in ("premium", "luxury", "5-star", "five-star")):
        warnings.append(
            "Premium or luxury preferences may push the trip above the stated budget."
        )
    if budget and any(term in f"{query} {preferences}" for term in ("expensive", "high-end")):
        warnings.append(
            "Higher-cost activities or accommodation may require a tradeoff against the stated budget."
        )
    return warnings


def _infer_request_scope(query: str) -> dict[str, bool]:
    """Choose a conservative scope when supervisor parsing is unavailable."""
    text = query.lower()
    scope = _empty_scope()
    scope["flight"] = any(
        term in text
        for term in (
            "flight",
            "airfare",
            "airline",
            "airport",
            "route",
            "departure",
            "arrival",
        )
    )
    scope["hotel"] = any(
        term in text
        for term in ("hotel", "accommodation", "lodging", "where to stay", "stay in")
    )
    scope["weather"] = any(
        term in text
        for term in ("weather", "forecast", "climate", "temperature", "rainfall")
    ) or ("packing" in text and "weather" in text)
    scope["budget"] = any(
        term in text
        for term in (
            "budget",
            "afford",
            "how much",
            "total cost",
            "trip cost",
            "expenses",
        )
    )
    explicit_limit = any(term in text for term in ("under ₹", "under rs", "under inr"))
    scope["budget"] = scope["budget"] or (
        explicit_limit and any(term in text for term in ("trip", "travel", "cost"))
    )
    scope["itinerary"] = any(
        term in text
        for term in (
            "itinerary",
            "day-by-day",
            "day by day",
            "schedule",
            "plan my trip",
            "plan a ",
            "complete travel plan",
        )
    )
    if scope["itinerary"] and any(
        phrase in text for phrase in ("already booked", "booked my flight", "booked my hotel")
    ):
        scope["flight"] = False
        scope["hotel"] = False
    if scope["budget"] and any(
        phrase in text for phrase in ("can i travel", "trip cost", "total cost", "how much")
    ):
        scope["flight"] = scope["flight"] or "flight" not in text
        scope["hotel"] = scope["hotel"] or "hotel" not in text
    return scope


def _agents_from_scope(scope: dict[str, bool]) -> list[str]:
    return [
        agent
        for agent in AGENT_ORDER
        if scope.get(agent.removesuffix("_agent"), False)
    ]


# ============================================================
# Supervisor and guardrail
# ============================================================

def supervisor_agent(state: TravelState) -> dict[str, Any]:
    query = state["user_query"]
    llm_calls = state.get("llm_calls", 0)
    guardrail_prompt = f"""
Determine whether this request is travel planning or travel information.
Allow flights, hotels, destinations, weather, budgets, transportation,
sightseeing, food, packing, and itineraries. Reject clearly unrelated,
harmful, or illegal requests. Missing trip details are allowed.

Return strict JSON only: {{"allowed": true, "reason": ""}}

User request:
{query}
"""

    try:
        guardrail = _json_from_llm(
            _llm_text(
                "You are a lightweight travel input guardrail. Return strict JSON only.",
                guardrail_prompt,
            )
        )
        allowed = bool(guardrail.get("allowed", True))
        reason = str(guardrail.get("reason", "")).strip()
        llm_calls += 1
    except Exception as exc:
        print(f"Guardrail fallback used: {type(exc).__name__}: {exc}")
        allowed = True
        reason = "Guardrail validation fallback allowed the request."

    if not allowed:
        reason = reason or (
            "This assistant can only help with travel-planning requests. "
            "Ask about a destination, flight, hotel, weather, budget, or itinerary."
        )
        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "selected_agents": [],
            "requested_scope": _empty_scope(),
            "constraint_warnings": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": reason,
            "final_answer": reason,
            "llm_calls": llm_calls,
        }

    supervisor_prompt = f"""
Select the minimum specialist agents needed for the user's actual request.
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
{{
  "selected_agents": ["flight_agent"],
  "requested_scope": {{
    "flight": true, "hotel": false, "weather": false,
    "budget": false, "itinerary": false
  }},
  "trip_constraints": {{
    "destination": "", "origin": "", "duration": "", "budget": "",
    "travel_style": "", "special_preferences": []
  }},
  "reasoning": ""
}}

User request:
{query}
"""

    try:
        parsed = _json_from_llm(
            _llm_text(
                "You route work to known travel specialist agents. Return strict JSON only.",
                supervisor_prompt,
            )
        )
        requested_agents = parsed.get("selected_agents", [])
        if not isinstance(requested_agents, list):
            raise ValueError("selected_agents must be a list.")
        selected_agents = [
            name for name in AGENT_ORDER
            if name in requested_agents and name in KNOWN_AGENTS
        ]
        requested_scope = _empty_scope()
        parsed_scope = parsed.get("requested_scope", {})
        if isinstance(parsed_scope, dict):
            for key in requested_scope:
                requested_scope[key] = bool(parsed_scope.get(key, False))
        if not any(requested_scope.values()):
            requested_scope = _empty_scope()
            for agent in selected_agents:
                requested_scope[agent.removesuffix("_agent")] = True

        # Keep routing and scope consistent, while preserving the supervisor's
        # minimum selection rather than expanding it into a full trip workflow.
        selected_agents = [
            agent for agent in AGENT_ORDER
            if agent in selected_agents
            and requested_scope.get(agent.removesuffix("_agent"), False)
        ]
        for agent in _agents_from_scope(requested_scope):
            if agent not in selected_agents:
                selected_agents.append(agent)

        constraints = _empty_constraints()
        parsed_constraints = parsed.get("trip_constraints", {})
        if isinstance(parsed_constraints, dict):
            for key in constraints:
                if key in parsed_constraints:
                    constraints[key] = parsed_constraints[key]
        reasoning = str(parsed.get("reasoning", "")).strip()
        llm_calls += 1
    except Exception as exc:
        print(f"Supervisor fallback used: {type(exc).__name__}: {exc}")
        requested_scope = _infer_request_scope(query)
        selected_agents = _agents_from_scope(requested_scope)
        constraints = _empty_constraints()
        reasoning = (
            "Supervisor parsing failed, so a conservative keyword-based scope "
            "was selected as a safe fallback."
        )

    return {
        "guardrail_allowed": True,
        "guardrail_reason": reason,
        "selected_agents": selected_agents,
        "requested_scope": requested_scope,
        "trip_constraints": constraints,
        "supervisor_reasoning": reasoning,
        "llm_calls": llm_calls,
    }


def guardrail_blocked_agent(state: TravelState) -> dict[str, str]:
    return {
        "final_answer": state.get(
            "guardrail_reason",
            "This request was blocked by the travel input guardrail.",
        )
    }


# ============================================================
# Existing specialist agents
# ============================================================

def flight_agent(state: TravelState) -> dict[str, Any]:
    constraints = state.get("trip_constraints", {})
    route_query = (
        f"{constraints.get('origin', '')} to {constraints.get('destination', '')}"
        if constraints.get("origin") or constraints.get("destination")
        else state["user_query"]
    )
    flight_data = asyncio.run(flight_mcp_search((route_query)))
    return {
        "flight_results": flight_data,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def hotel_agent(state: TravelState) -> dict[str, Any]:
    query = (
        f"Find accommodation for this request:\n{state['user_query']}\n"
        f"Constraints:\n{_constraint_context(state)}"
    )
    try:
        hotel_results = asyncio.run(tavily_mcp_search(query))
    except Exception as exc:
        print(f"Hotel MCP error: {type(exc).__name__}: {exc}", flush=True)
        hotel_results = (
            "Live hotel search is temporarily unavailable. Provide general "
            "accommodation guidance and clearly label it as non-live advice."
        )
    return {
        "hotel_results": hotel_results,
        "llm_calls": state.get("llm_calls", 0),
    }


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


def budget_agent(state: TravelState) -> dict[str, Any]:
    constraint_warnings = _detect_constraint_warnings(state)
    prompt = f"""
Analyze whether this trip is realistic for the user's budget.
User Query: {_prompt_text(state['user_query'], 1200)}
Trip Constraints:
{_constraint_context(state)}
Flight Results: {_prompt_text(state.get('flight_results', ''), 3000)}
Hotel Results: {_prompt_text(state.get('hotel_results', ''), 1800)}
Weather Results: {_prompt_text(state.get('weather_results', ''), 1800)}

Return a concise analysis containing:
- estimated total cost and range
- the user's stated budget limit, or explicitly say no budget was provided
- major cost drivers
- feasibility
- budget conflicts or tradeoffs
- money-saving suggestions
Never silently replace a requested premium preference with a cheaper option.
Clearly label retrieved prices, estimates, and unavailable prices.
Keep the response concise, under 700 words, and do not leave sentences or
table rows unfinished.
"""
    log_prompt_metrics("budget_agent", prompt, state)
    response = llm.invoke(
        [
            SystemMessage(content="You are a practical travel budget analyst."),
            HumanMessage(content=prompt),
        ]
    )
    return {
        "budget_results": response.content,
        "constraint_warnings": constraint_warnings,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def itinerary_agent(state: TravelState) -> dict[str, Any]:
    scope = state.get("requested_scope", _empty_scope())
    prompt = f"""
Create only the itinerary or trip plan requested by the user.
Do not add unrelated hotels, flights, weather, budget, visa, restaurant,
or activity sections unless they are explicitly in the requested scope.
Requested scope: {scope}
User Query: {_prompt_text(state['user_query'], 1200)}
Trip Constraints:
{_constraint_context(state)}
Constraint warnings: {state.get('constraint_warnings', [])}
Flight Results: {_prompt_text(state.get('flight_results', ''), 2200)}
Hotel Results: {_prompt_text(state.get('hotel_results', ''), 1400)}
Weather Results: {_prompt_text(state.get('weather_results', ''), 1600)}
Budget Results: {_prompt_text(state.get('budget_results', ''), 3200)}

Respect the requested duration, budget, destination, travel style, and
preferences. If requirements conflict, explain the tradeoff instead of
silently changing them. Use only available information, preserve useful facts,
label estimates, and keep it practical and under 1,500 words. Do not reproduce
incomplete source fragments. This is a draft for human review.
"""
    log_prompt_metrics("itinerary_agent", prompt, state)
    response = llm.invoke(
        [
            SystemMessage(content="You are an expert travel planner."),
            HumanMessage(content=prompt),
        ]
    )
    return {
        "itinerary": response.content,
        "approval_request": (
            "Approve it to create the final "
            "plan, or provide feedback for revision."
        ),
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def human_approval_agent(state: TravelState) -> dict[str, Any]:
    review = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "selected_agents": state.get("selected_agents", []),
            "trip_constraints": state.get("trip_constraints", {}),
            "constraint_warnings": state.get("constraint_warnings", []),
            "expected_response": {
                "approved": True,
                "feedback": "Optional revision feedback",
            },
        }
    )
    if not isinstance(review, dict):
        raise ValueError("Human approval must be an object.")
    return {
        "approved": bool(review.get("approved", False)),
        "human_feedback": str(review.get("feedback", "")).strip(),
    }


def final_agent(state: TravelState) -> dict[str, Any]:
    scope = state.get("requested_scope", _empty_scope())
    if state.get("approved", False):
        review_instruction = (
            "The user approved the draft. Preserve its decisions while polishing it."
        )
    else:
        review_instruction = (
            "Revise the draft using this feedback: "
            f"{state.get('human_feedback', '') or 'Improve the draft before finalizing it.'}"
        )

    prompt = f"""
Generate the final travel response.
Review instruction: {review_instruction}
Requested scope: {scope}
Selected agents: {state.get('selected_agents', [])}
User Request: {_prompt_text(state['user_query'], 1200)}
Trip Constraints:
{_constraint_context(state)}
Constraint warnings: {state.get('constraint_warnings', [])}
Flights: {_prompt_text(state.get('flight_results', ''), 1800)}
Hotels: {_prompt_text(state.get('hotel_results', ''), 1200)}
Weather: {_prompt_text(state.get('weather_results', ''), 1400)}
Budget Analysis: {_prompt_text(state.get('budget_results', ''), 2600)}
Draft Itinerary: {_prompt_text(state.get('itinerary', ''), 7000)}

Answer only the user's requested information. Do not add unrelated travel
planning sections. Use only the available specialist results. If an itinerary
was not requested, do not create one. If an itinerary was requested, preserve the draft's useful facts and keep the
plan within the requested scope. Preserve the user's constraints and disclose
tradeoffs rather than silently changing requirements. Distinguish retrieved
facts, estimates, and unavailable information.
Keep the response concise and clearly label estimates.
"""
    log_prompt_metrics("final_agent", prompt, state)
    response = llm.invoke(
        [
            SystemMessage(content="You are a professional AI travel planner."),
            HumanMessage(content=prompt),
        ]
    )
    return {
        "final_answer": response.content,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# ============================================================
# Deterministic dynamic routing
# ============================================================

ROUTE_MAP = {
    "guardrail_blocked": "guardrail_blocked",
    "final_agent": "final_agent",
    **{agent: agent for agent in AGENT_ORDER},
}


def _selected_agents(state: TravelState) -> list[str]:
    selected = state.get("selected_agents", [])
    return [agent for agent in AGENT_ORDER if agent in selected]


def route_from_supervisor(state: TravelState) -> str:
    if not state.get("guardrail_allowed", True):
        return "guardrail_blocked"
    selected = _selected_agents(state)
    return selected[0] if selected else "final_agent"


def route_after_agent(current_agent: str):
    def route(state: TravelState) -> str:
        selected = _selected_agents(state)
        current_index = AGENT_ORDER.index(current_agent)
        for next_agent in AGENT_ORDER[current_index + 1 :]:
            if next_agent in selected:
                return next_agent
        return "final_agent"

    return route


def route_after_itinerary(state: TravelState) -> str:
    return "human_approval"


graph = StateGraph(TravelState)
graph.add_node("supervisor", supervisor_agent)
graph.add_node("guardrail_blocked", guardrail_blocked_agent)
graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("budget_agent", budget_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("human_approval", human_approval_agent)
graph.add_node("final_agent", final_agent)
graph.add_edge(START, "supervisor")
graph.add_conditional_edges("supervisor", route_from_supervisor, ROUTE_MAP)
for agent in AGENT_ORDER[:-1]:
    graph.add_conditional_edges(agent, route_after_agent(agent), ROUTE_MAP)
graph.add_conditional_edges(
    "itinerary_agent",
    route_after_itinerary,
    {"human_approval": "human_approval"},
)
graph.add_edge("human_approval", "final_agent")
graph.add_edge("final_agent", END)
graph.add_edge("guardrail_blocked", END)


# ============================================================
# PostgreSQL checkpointer
# ============================================================

_conn = psycopg.connect(
    get_database_url(),
    autocommit=True,
    row_factory=dict_row,
)
checkpointer = PostgresSaver(_conn)
checkpointer.setup()
travel_graph = graph.compile(checkpointer=checkpointer)


# ============================================================
# FastAPI-facing serialization and runners
# ============================================================

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
    answer = result.get("final_answer", "") or itinerary
    return {
        "thread_id": thread_id,
        "answer": answer,
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
        "requested_scope": result.get("requested_scope", _empty_scope()),
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
    config = {"configurable": {"thread_id": thread_id}}
    result = travel_graph.invoke(
        {
            "user_query": user_input,
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "itinerary": "",
            "final_answer": "",
            "budget_results": "",
            "requested_scope": _empty_scope(),
            "constraint_warnings": [],
            "llm_calls": 0,
        },
        config=config,
    )
    return _serialize_result(result, thread_id)


def resume_travel_agent(
    thread_id: str,
    approved: bool,
    feedback: str = "",
) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    result = travel_graph.invoke(
        Command(resume={"approved": approved, "feedback": feedback}),
        config=config,
    )
    return _serialize_result(result, thread_id)
