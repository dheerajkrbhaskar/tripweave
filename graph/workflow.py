"""LangGraph construction and PostgreSQL checkpoint configuration."""

import os

import psycopg
from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row

from agents.budget_agent import budget_agent
from agents.final_agent import final_agent
from agents.flight_agent import flight_agent
from agents.hotel_agent import hotel_agent
from agents.itinerary_agent import human_approval_agent, itinerary_agent
from agents.supervisor import AGENT_ORDER, guardrail_blocked_agent, supervisor_agent
from agents.weather_agent import weather_agent
from graph.routing import ROUTE_MAP, route_after_agent, route_after_itinerary, route_from_supervisor
from graph.state import TravelState


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is missing. Please add it to your .env file.")
    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"
    return database_url


load_dotenv()
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
graph.add_conditional_edges("itinerary_agent", route_after_itinerary, {"human_approval": "human_approval"})
graph.add_edge("human_approval", "final_agent")
graph.add_edge("final_agent", END)
graph.add_edge("guardrail_blocked", END)

_conn = psycopg.connect(get_database_url(), autocommit=True, row_factory=dict_row)
checkpointer = PostgresSaver(_conn)
checkpointer.setup()
travel_graph = graph.compile(checkpointer=checkpointer)
