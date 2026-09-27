from tools.flight_tool import search_flights
from backend import run_travel_agent
# res = search_flights("Plan a 7 day dubai trip from india")
# print(res)

user_input = 'Plan a 7 day trip from india to dubai affordable student friendly'
res = run_travel_agent(user_input,"test1")
print(res["answer"])