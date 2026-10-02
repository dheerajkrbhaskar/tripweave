"""Shared helpers used by the workflow agents."""

import json
import os
from typing import Any

import certifi
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from graph.state import TravelState

load_dotenv()
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing. Please add it to your .env file.")

GROQ_MODEL = os.getenv("GROQ_MODEL")
if not GROQ_MODEL:
    raise ValueError("GROQ_MODEL is missing. Please add it to your .env file.")

llm = ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY)


def prompt_text(value: object, limit: int) -> str:
    """Keep accumulated tool output within the provider's prompt budget."""
    text = str(value or "")
    if len(text) <= limit:
        return text
    excerpt = text[:limit]
    boundary = max(excerpt.rfind("\n"), excerpt.rfind(". "), excerpt.rfind(" "))
    if boundary <= 0:
        boundary = limit
    return excerpt[:boundary].rstrip() + "\n[Additional source output omitted]"


def llm_text(system_prompt: str, user_prompt: str) -> str:
    response = llm.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return str(response.content)


def json_from_llm(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The model did not return a JSON object.")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("The model returned a JSON value that was not an object.")
    return value


def empty_constraints() -> dict[str, Any]:
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": [],
    }


def empty_scope() -> dict[str, bool]:
    return {
        "flight": False,
        "hotel": False,
        "weather": False,
        "budget": False,
        "itinerary": False,
    }


def constraint_context(state: TravelState) -> str:
    constraints = state.get("trip_constraints", {})
    return (
        f"Destination: {constraints.get('destination') or 'not provided'}\n"
        f"Origin: {constraints.get('origin') or 'not provided'}\n"
        f"Duration: {constraints.get('duration') or 'not provided'}\n"
        f"Budget: {constraints.get('budget') or 'not provided'}\n"
        f"Travel style: {constraints.get('travel_style') or 'not provided'}\n"
        f"Preferences: {constraints.get('special_preferences') or 'none provided'}"
    )


def detect_constraint_warnings(state: TravelState) -> list[str]:
    query = state.get("user_query", "").lower()
    constraints = state.get("trip_constraints", {})
    budget = str(constraints.get("budget") or "").strip()
    preferences = str(constraints.get("special_preferences") or "").lower()
    combined = f"{query} {preferences}"
    warnings: list[str] = []
    if budget and any(term in combined for term in ("premium", "luxury", "5-star", "five-star")):
        warnings.append(
            "Premium or luxury preferences may push the trip above the stated budget."
        )
    if budget and any(term in combined for term in ("expensive", "high-end")):
        warnings.append(
            "Higher-cost activities or accommodation may require a tradeoff against the stated budget."
        )
    return warnings


def log_prompt_metrics(name: str, prompt: str, state: TravelState) -> None:
    print(
        f"{name} prompt: chars={len(prompt)} "
        f"estimated_tokens={max(1, len(prompt) // 4) if prompt else 0} components={{"
        f"'user_query': {len(state.get('user_query', ''))}, "
        f"'flight_results': {len(state.get('flight_results', ''))}, "
        f"'hotel_results': {len(state.get('hotel_results', ''))}, "
        f"'weather_results': {len(state.get('weather_results', ''))}, "
        f"'budget_results': {len(state.get('budget_results', ''))}}}"
    )
