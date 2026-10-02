"""Final response generation agent."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.common import constraint_context, empty_scope, llm, log_prompt_metrics, prompt_text
from graph.state import TravelState


def final_agent(state: TravelState) -> dict[str, Any]:
    scope = state.get("requested_scope", empty_scope())
    review_instruction = (
        "The user approved the draft. Preserve its decisions while polishing it."
        if state.get("approved", False)
        else "Revise the draft using this feedback: "
        f"{state.get('human_feedback', '') or 'Improve the draft before finalizing it.'}"
    )
    prompt = f"""Generate the final travel response.
Review instruction: {review_instruction}
Requested scope: {scope}
Selected agents: {state.get('selected_agents', [])}
User Request: {prompt_text(state['user_query'], 1200)}
Trip Constraints:
{constraint_context(state)}
Constraint warnings: {state.get('constraint_warnings', [])}
Flights: {prompt_text(state.get('flight_results', ''), 1800)}
Hotels: {prompt_text(state.get('hotel_results', ''), 1200)}
Weather: {prompt_text(state.get('weather_results', ''), 1400)}
Budget Analysis: {prompt_text(state.get('budget_results', ''), 2600)}
Draft Itinerary: {prompt_text(state.get('itinerary', ''), 7000)}

Answer only the user's requested information. Do not add unrelated travel
planning sections. Use only the available specialist results. If an itinerary
was not requested, do not create one. If an itinerary was requested, preserve
the draft's useful facts and keep the plan within the requested scope. Preserve
the user's constraints and disclose tradeoffs rather than silently changing
requirements. Distinguish retrieved facts, estimates, and unavailable
information. Keep the response concise and clearly label estimates."""
    log_prompt_metrics("final_agent", prompt, state)
    response = llm.invoke(
        [SystemMessage(content="You are a professional AI travel planner."), HumanMessage(content=prompt)]
    )
    return {
        "final_answer": response.content,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }
