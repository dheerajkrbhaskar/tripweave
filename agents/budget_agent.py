"""Budget analysis specialist agent."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.common import constraint_context, detect_constraint_warnings, llm, log_prompt_metrics, prompt_text
from graph.state import TravelState


def budget_agent(state: TravelState) -> dict[str, Any]:
    constraint_warnings = detect_constraint_warnings(state)
    prompt = f"""Analyze whether this trip is realistic for the user's budget.
User Query: {prompt_text(state['user_query'], 1200)}
Trip Constraints:
{constraint_context(state)}
Flight Results: {prompt_text(state.get('flight_results', ''), 3000)}
Hotel Results: {prompt_text(state.get('hotel_results', ''), 1800)}
Weather Results: {prompt_text(state.get('weather_results', ''), 1800)}

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
table rows unfinished."""
    log_prompt_metrics("budget_agent", prompt, state)
    response = llm.invoke(
        [SystemMessage(content="You are a practical travel budget analyst."), HumanMessage(content=prompt)]
    )
    return {
        "budget_results": response.content,
        "constraint_warnings": constraint_warnings,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }
